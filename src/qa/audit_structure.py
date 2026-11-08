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


def audit(data_root, out_dir: Path) -> list[dict]:
    elements: dict[str, dict] = {}
    edges: dict[tuple, list[str]] = {}
    for shard in sorted(Path(out_dir).glob("shard-*")):
        for row in pq.read_table(shard / "elements.parquet").to_pylist():
            elements[row["element_id"]] = row
        for row in pq.read_table(shard / "hierarchy.parquet").to_pylist():
            edges.setdefault((row["arxiv_id"], row["version"]), []).append(row["element_id"])
    results = []
    for (arxiv_id, version), ids in sorted(edges.items()):
        vdir = next(
            (
                root / to_folder_name(arxiv_id) / f"v{version}"
                for root in as_paths(data_root)
                if (root / to_folder_name(arxiv_id)).is_dir()
            ),
            Path("/nonexistent"),
        )
        if not vdir.is_dir():
            continue
        tex = TexVersion(vdir, paper_title(vdir))
        found = tex.gather()
        if found.root is None:
            continue
        src = count_source(tex.expand(found.root))
        got = count_tree([elements[i] for i in ids if i in elements])
        row = {"arxiv_id": arxiv_id, "version": version}
        for measure in src:
            row[f"{measure}_source"], row[f"{measure}_tree"] = src[measure], got[measure]
            row[f"{measure}_agree"] = int(src[measure] == got[measure])
        results.append(row)
    return results


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
