# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
r"""Does the tree keep what the source has? Counts in the LaTeX versus counts in the tree.

    python -m src.qa.audit_structure --data-root data/corpus --out-dir data/m2 --report audit

For every parsed version of the runner's output the source is read again (``gather`` +
``expand``, no parser stage) and four things are counted by plain regular expressions:

- headings (``\chapter`` ... ``\subparagraph``) outside the References section;
- displayed formulas (``equation``-like environments, ``$$``, ``\[``);
- floats (``figure``, ``table``, ``algorithm``... and bare ``tabular``);
- list items (``\item`` inside ``itemize``/``enumerate``/``description``).

and compared with the number of nodes of that kind in the version's tree. A version *agrees* on
a measure when the counts are equal. This is a consistency check, not a judgement of the
sentences: a mismatch points at a structure that was lost or invented, and the audit sheet of
``src.qa.audit_sample`` is where the text is read by a person.

Writes ``<report>/structure_audit.csv`` (one row per version) and prints the agreement rates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

from src.parser.gather import TexVersion, paper_title, strip_comments
from src.parser.hierarchy import (
    _DEFINITIONS,
    ABSTRACT_ENVS,
    ACK_ENVS,
    EQUATION_ENVS,
    FIGURE_ENVS,
    LIST_ENVS,
    REFERENCE_TITLES,
)
from src.parser.normalize import _end_of_env, drop_command, match_brace, strip_formatting
from src.parser.run import as_paths
from src.utils.ids import to_folder_name

_HEADING = re.compile(
    r"\\(chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*(?:\[[^\]]*\])?\s*\{"
)
_ENV = re.compile(r"\\begin\s*\{([A-Za-z@]+\*?)\}")
_ITEM = re.compile(r"\\item(?![A-Za-z])")


def count_source(text: str) -> dict[str, int]:
    """Headings, formulas, floats and items of a LaTeX source (comments already removed)."""
    text = strip_comments(text)
    start = re.search(r"\\begin\s*\{document\}", text)
    body = text[start.end() :] if start else text
    body = drop_command(body, _DEFINITIONS, args=2)  # a \newcommand body is not content
    headings, skipping = 0, None
    ranks = {"chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4, "paragraph": 5}
    # headings after a References heading, up to the next heading of the same or higher rank
    for m in _HEADING.finditer(body):
        rank = ranks.get(m.group(1), 6)
        end = match_brace(body, m.end() - 1)  # the title may hold braces: \textbf{..}, $x_{i}$
        title = " ".join(strip_formatting(body[m.end() : end - 1 if end > 0 else m.end()]).split())
        title = title.lower().strip(" .:")
        if skipping is not None:
            if rank > skipping:
                continue
            skipping = None
        if title in REFERENCE_TITLES:
            skipping = rank
            continue
        headings += 1
    # the abstract and the acknowledgements environments become sections of their own
    headings += sum(1 for m in _ENV.finditer(body) if m.group(1) in ABSTRACT_ENVS | ACK_ENVS)
    body = _blank_envs(body, ("thebibliography", "verbatim", "lstlisting", "comment"))
    body, floats = _remove_floats(body)
    envs = [m.group(1) for m in _ENV.finditer(body)]
    formulas = sum(1 for e in envs if e in EQUATION_ENVS and e != "split")
    formulas += len(re.findall(r"(?<!\\)\$\$", body)) // 2
    formulas += len(re.findall(r"(?<!\\)\\\[", body))  # \[ but not the \\[2pt] line break
    items = len(_ITEM.findall(body)) if any(e in LIST_ENVS for e in envs) else 0
    return {"headings": headings, "formulas": formulas, "floats": floats, "items": items}


def _blank_envs(text: str, names: tuple[str, ...]) -> str:
    for name in names:
        text = re.sub(
            r"\\begin\s*\{" + name + r"\}.*?\\end\s*\{" + name + r"\}", "", text, flags=re.S
        )
    return text


def _remove_floats(text: str) -> tuple[str, int]:
    """Cut out the outermost float environments; return the rest and how many there were."""
    out, pos, n = [], 0, 0
    for m in _ENV.finditer(text):
        if m.start() < pos or m.group(1) not in FIGURE_ENVS:
            continue
        name = m.group(1)
        closing = _end_of_env(text, name.rstrip("*"), "*" if name.endswith("*") else "", m.end())
        if closing is None:
            continue
        out.append(text[pos : m.start()])
        pos, n = closing[1], n + 1
    out.append(text[pos:])
    return "".join(out), n


def count_tree(rows: list[dict]) -> dict[str, int]:
    """The same measures from the ``elements`` rows reachable in one version."""
    kinds = [r["kind"] for r in rows]
    headings = {"chapter", "section", "subsection", "subsubsection", "paragraph"}
    return {
        "headings": sum(k in headings for k in kinds),
        "formulas": kinds.count("equation"),
        "floats": kinds.count("figure"),
        "items": kinds.count("item"),
    }


def _audit_shard(data_root, shard: Path, expected_status=None):
    elements: dict[str, dict] = {}
    edges: dict[tuple, list[str]] = {}
    for row in pq.read_table(
        shard / "elements.parquet", columns=["element_id", "kind"]
    ).to_pylist():
        elements[row["element_id"]] = row
    for row in pq.read_table(
        shard / "hierarchy.parquet", columns=["arxiv_id", "version", "element_id"]
    ).to_pylist():
        edges.setdefault((row["arxiv_id"], row["version"]), []).append(row["element_id"])
    for (arxiv_id, version), ids in sorted(edges.items()):
        if expected_status is not None:
            status = expected_status.get((arxiv_id, version))
            if status is None or status == "missing":
                raise ValueError(f"Unexpected hierarchy version: {arxiv_id}v{version}")
            if status != "parsed":
                continue
        vdir = next(
            (
                root / to_folder_name(arxiv_id) / f"v{version}"
                for root in as_paths(data_root)
                if (root / to_folder_name(arxiv_id)).is_dir()
            ),
            Path("/nonexistent"),
        )
        if not vdir.is_dir():
            raise FileNotFoundError(f"Source version missing: {arxiv_id}v{version}")
        tex = TexVersion(vdir, paper_title(vdir))
        found = tex.gather()
        if found.root is None:
            if expected_status is not None and expected_status.get((arxiv_id, version)) == "parsed":
                raise ValueError(f"Expected parsed source root: {arxiv_id}v{version}")
            continue
        src = count_source(tex.expand(found.root))
        got = count_tree([elements[i] for i in ids if i in elements])
        row = {"arxiv_id": arxiv_id, "version": version}
        for measure in src:
            row[f"{measure}_source"], row[f"{measure}_tree"] = src[measure], got[measure]
            row[f"{measure}_agree"] = int(src[measure] == got[measure])
        yield row


def iter_audit(data_root, out_dir: Path):
    """Yield source comparisons one shard at a time."""
    for shard in sorted(Path(out_dir).glob("shard-*")):
        yield from _audit_shard(data_root, shard)


def audit(data_root, out_dir: Path) -> list[dict]:
    return list(iter_audit(data_root, out_dir))


def audit_resumable(
    data_root,
    out_dir: Path,
    report: Path,
    identity: dict,
    on_progress=None,
    max_shard_rows: int = 500_000,
    journal: Path | None = None,
    expected_hashes: dict | None = None,
) -> dict:
    """Audit one shard at a time, checkpointing against the supplied verified input identity."""
    if not identity:
        raise ValueError("Structural audit identity required")
    out_dir, report = Path(out_dir), Path(report)
    if report.resolve() == out_dir.resolve() or report.resolve().is_relative_to(out_dir.resolve()):
        raise ValueError("Structural audit report overlaps input")
    report.mkdir(parents=True, exist_ok=True)
    expected_status = None
    metadata = {"identity": identity, "journal_sha256": None}
    if journal is not None:
        from src.qa.qa_inputs import read_assignments

        data = Path(journal).read_bytes()
        read_assignments(journal)
        if data != Path(journal).read_bytes():
            raise ValueError("Journal changed during structural audit setup")
        metadata["journal_sha256"] = hashlib.sha256(data).hexdigest()
        expected_status = {}
        for line in data.splitlines():
            for paper in json.loads(line)["papers"]:
                for version in paper["versions"]:
                    expected_status[(paper["arxiv_id"], version["version"])] = version["status"]
    checkpoint = report / "structure-checkpoints"
    checkpoint.mkdir(exist_ok=True)
    meta = checkpoint / "identity.json"
    if meta.exists():
        if json.loads(meta.read_text(encoding="utf8")) != metadata:
            raise ValueError("Structural audit identity changed")
    else:
        if any(checkpoint.glob("shard-*.json")):
            raise ValueError("Structural audit identity missing")
        temp = meta.with_suffix(".part")
        temp.write_text(json.dumps(metadata, sort_keys=True), encoding="utf8")
        os.replace(temp, meta)
    shards = sorted(out_dir.glob("shard-*"))
    if not shards:
        raise ValueError("No shards to audit")
    if expected_hashes is not None and {shard.name for shard in shards} != set(expected_hashes):
        raise ValueError("Structural audit shard manifest mismatch")
    for done, shard in enumerate(shards, 1):
        if expected_hashes is not None:
            from src.qa.qa_inputs import verify_shard

            verify_shard(shard, expected_hashes[shard.name])
        hashes = {}
        rows = sum(
            pq.ParquetFile(shard / f"{table}.parquet").metadata.num_rows
            for table in ("elements", "hierarchy")
        )
        if rows > max_shard_rows:
            raise ValueError(f"Structural audit shard row limit exceeded: {shard.name}")
        for table in ("elements", "hierarchy"):
            with (shard / f"{table}.parquet").open("rb") as stream:
                hashes[table] = hashlib.file_digest(stream, "sha256").hexdigest()
        target = checkpoint / f"{shard.name}.json"
        if target.exists():
            saved = json.loads(target.read_text(encoding="utf8"))
            if saved["hashes"] != hashes:
                raise ValueError(f"Structural audit shard changed: {shard.name}")
        else:
            saved = {
                "hashes": hashes,
                "rows": list(_audit_shard(data_root, shard, expected_status)),
            }
            if expected_hashes is not None:
                verify_shard(shard, expected_hashes[shard.name])
            temp = target.with_suffix(".part")
            temp.write_text(json.dumps(saved), encoding="utf8")
            os.replace(temp, target)
        if expected_hashes is not None:
            verify_shard(shard, expected_hashes[shard.name])
        if on_progress:
            on_progress(done, len(shards))
    temp_csv = report / ".structure_audit.part"
    count = 0
    observed = set()
    agreement = {key: 0 for key in ("headings", "formulas", "floats", "items")}
    with temp_csv.open("w", encoding="utf8", newline="") as stream:
        writer = None
        for shard in shards:
            saved = json.loads((checkpoint / f"{shard.name}.json").read_text(encoding="utf8"))
            for row in saved["rows"]:
                key = (row["arxiv_id"], row["version"])
                if key in observed:
                    raise ValueError(f"Duplicate structure result: {key}")
                observed.add(key)
                if writer is None:
                    writer = csv.DictWriter(stream, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                count += 1
                for key in agreement:
                    agreement[key] += row[f"{key}_agree"]
    if expected_status is not None:
        expected_parsed = {key for key, status in expected_status.items() if status == "parsed"}
        missing = expected_parsed - observed
        extra = observed - expected_parsed
        if missing or extra:
            raise ValueError(f"Parsed versions missing or unexpected: {len(missing)}, {len(extra)}")
    os.replace(temp_csv, report / "structure_audit.csv")
    summary = {
        "versions": count,
        "agreement": agreement,
        "agreement_rates": {
            key: value / count if count else None for key, value in agreement.items()
        },
    }
    temp_summary = report / ".structure_summary.part"
    temp_summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf8")
    os.replace(temp_summary, report / "structure_summary.json")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("audit"))
    args = parser.parse_args(argv)
    rows = audit(args.data_root, args.out_dir)
    args.report.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(args.report / "structure_audit.csv", "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(f"{len(rows)} versions compared")
    for measure in ("headings", "formulas", "floats", "items"):
        agree = sum(r[f"{measure}_agree"] for r in rows)
        rate = 100 * agree / max(len(rows), 1)
        print(f"  {measure:9s} agree in {agree}/{len(rows)} versions ({rate:.1f} %)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
