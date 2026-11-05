# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Read-by-eye audit of the M2 output: draw papers, print them for reading, score the sheet.

    python -m src.qa.audit_sample draw --out-dir data/m2 --work-dir work/m2 \\
        --data-root data/corpus --report audit -n 30 --seed 2026
    python -m src.qa.audit_sample score audit/audit_sheet.csv --out audit/audit_summary.csv

``draw`` picks ``n`` papers at random (reproducible with ``--seed``) among those the runner
parsed without error, and writes into ``--report``:

- ``<folder>.md``: for each parsed version the tree rebuilt from the ``elements`` and
  ``hierarchy`` tables (indented, with the versions that share each element) and the paper's
  ``bibtex`` rows, next to the path of the root ``.tex`` to compare with;
- ``audit_sheet.csv``: one row per paper, blank judgement columns.

Fill each criterion with ``y`` (correct), ``n`` (wrong, say what in ``notes``) or leave it blank
or ``na`` when it does not apply. ``score`` turns the sheet into the share of correct papers per
criterion and overall, and lists the errors, for the book. The tables are read from
``<out-dir>/shard-*/{elements,hierarchy,bibtex}.parquet``.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.parser.run import Journal

CRITERIA = (
    "hierarchy_ok",  # sections / subsections / paragraphs at the right levels, no References
    "sentences_ok",  # no split inside math, commands, abbreviations, URLs, decimals
    "math_ok",  # inline math as $...$, block math as equation
    "figures_ok",  # figures, tables and lists are leaves / branches as the statement says
    "appendix_ok",  # Acknowledgements and appendices (also \section*) are present
    "bibtex_ok",  # entries match the printed reference list
    "dedup_ok",  # equal content across versions shares one element
)
SHEET_COLUMNS = ["arxiv_id", "version", "root_file", "n_elements", "n_bibtex", *CRITERIA, "notes"]
MAX_DEPTH = 30
MAX_CONTENT = 110


def read_table(out_dir: Path, shard: int, table: str, arxiv_id: str) -> pd.DataFrame:
    path = Path(out_dir) / f"shard-{shard:05d}" / f"{table}.parquet"
    return pd.read_parquet(path, filters=[("arxiv_id", "==", arxiv_id)])


def render_tree(elements: pd.DataFrame, hierarchy: pd.DataFrame, version: int) -> list[str]:
    """Indented lines of one version; ``(vN, vM)`` marks elements shared with other versions."""
    kind = dict(zip(elements.element_id, elements.kind, strict=False))
    content = dict(zip(elements.element_id, elements.content, strict=False))
    shared = hierarchy.groupby("element_id").version.apply(lambda s: sorted(set(s)))
    rows = hierarchy[hierarchy.version == version]
    ids = set(rows.element_id)
    children: dict[str, list[str]] = defaultdict(list)
    for eid, parent in zip(rows.element_id, rows.parent_id, strict=False):
        if parent in ids and parent != eid:
            children[parent].append(eid)
    lines: list[str] = []

    def visit(eid: str, depth: int, seen: frozenset) -> None:
        text = " ".join(str(content.get(eid) or "").split())
        if len(text) > MAX_CONTENT:
            text = text[: MAX_CONTENT - 1] + "…"
        also = shared.get(eid, [])
        tag = f"  (v{', v'.join(map(str, also))})" if len(also) > 1 else ""
        lines.append(f"{'  ' * depth}[{kind.get(eid, '?')}] {text}{tag}  <{eid}>")
        if depth < MAX_DEPTH:
            for child in children.get(eid, []):
                if child not in seen:
                    visit(child, depth + 1, seen | {eid})

    roots = [e for e, p in zip(rows.element_id, rows.parent_id, strict=False) if p not in ids]
    for root in roots:
        visit(root, 0, frozenset())
    return lines


def eligible_papers(work_dir: Path) -> dict[str, dict]:
    papers, _ = Journal(Path(work_dir) / "shards.jsonl").load()
    return {
        i: rec
        for i, rec in papers.items()
        if not rec["error"] and any(v["status"] == "parsed" for v in rec["versions"])
    }


def draw(out_dir: Path, work_dir: Path, report: Path, n: int, seed: int, data_root: Path | None):
    papers = eligible_papers(work_dir)
    chosen = random.Random(seed).sample(sorted(papers), min(n, len(papers)))
    report.mkdir(parents=True, exist_ok=True)
    sheet = []
    for arxiv_id in sorted(chosen):
        rec = papers[arxiv_id]
        elements = read_table(out_dir, rec["shard"], "elements", arxiv_id)
        hierarchy = read_table(out_dir, rec["shard"], "hierarchy", arxiv_id)
        bibtex = read_table(out_dir, rec["shard"], "bibtex", arxiv_id)
        parsed = [v for v in rec["versions"] if v["status"] == "parsed"]
        lines = [f"# {arxiv_id}", ""]
        for v in rec["versions"]:
            where = f"{data_root}/{rec['folder']}/v{v['version']}/{v['root']}" if v["root"] else "-"
            lines += [f"## v{v['version']}: {v['status']}  root: `{where}`", ""]
            if v["status"] == "parsed":
                lines += ["```text", *render_tree(elements, hierarchy, v["version"]), "```", ""]
        lines += ["## BibTeX", ""]
        for row in bibtex.itertuples():
            authors = ", ".join(row.authors) if row.authors is not None else ""
            lines.append(f"- `{row.citation_key}` ({row.year}) {authors}: {row.title}")
        (report / f"{rec['folder']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        last = parsed[-1]
        sheet.append(
            {
                "arxiv_id": arxiv_id,
                "version": last["version"],
                "root_file": last["root"],
                "n_elements": len(elements),
                "n_bibtex": len(bibtex),
            }
        )
    with open(report / "audit_sheet.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(sheet)
    return sheet


def score(sheet: Path) -> tuple[list[dict], list[dict]]:
    """(per-criterion rows, the papers with at least one ``n``) of a filled sheet."""
    with open(sheet, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    summary = []
    for criterion in (*CRITERIA, "all"):
        verdicts = []
        for row in rows:
            marks = [(row[c] or "").strip().lower() for c in CRITERIA if criterion in (c, "all")]
            marks = [m for m in marks if m in ("y", "n")]
            if marks:
                verdicts.append(all(m == "y" for m in marks))
        summary.append(
            {
                "criterion": criterion,
                "checked": len(verdicts),
                "correct": sum(verdicts),
                "rate": round(sum(verdicts) / len(verdicts), 3) if verdicts else None,
            }
        )
    wrong = [
        {
            "arxiv_id": r["arxiv_id"],
            "criteria": [c for c in CRITERIA if (r[c] or "").strip().lower() == "n"],
            "notes": r["notes"],
        }
        for r in rows
        if any((r[c] or "").strip().lower() == "n" for c in CRITERIA)
    ]
    return summary, wrong


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("draw", help="pick papers and write the reading material")
    d.add_argument("--out-dir", type=Path, required=True, help="M2 output (shard-*/)")
    d.add_argument("--work-dir", type=Path, required=True, help="M2 work dir (shards.jsonl)")
    d.add_argument("--data-root", type=Path, default=Path("data/corpus"))
    d.add_argument("--report", type=Path, default=Path("audit"))
    d.add_argument("-n", type=int, default=30)
    d.add_argument("--seed", type=int, default=2026)
    s = sub.add_parser("score", help="rates from the filled sheet")
    s.add_argument("sheet", type=Path)
    s.add_argument("--out", type=Path, help="write the per-criterion rates as CSV")
    args = parser.parse_args(argv)

    if args.command == "draw":
        sheet = draw(args.out_dir, args.work_dir, args.report, args.n, args.seed, args.data_root)
        print(f"{len(sheet)} papers -> {args.report}/ (fill {args.report}/audit_sheet.csv)")
        return 0
    summary, wrong = score(args.sheet)
    for row in summary:
        print(f"{row['criterion']:<14} {row['correct']}/{row['checked']}  {row['rate']}")
    for row in wrong:
        print(f"WRONG {row['arxiv_id']}: {row['criteria']} {row['notes']}", file=sys.stderr)
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["criterion", "checked", "correct", "rate"])
            writer.writeheader()
            writer.writerows(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
