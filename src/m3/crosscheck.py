# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Cross-check of manual labels: a second person re-labels a random sample, blind.

1. Draw the sample (10 entries per labeler, labeler = owner of the paper's ID range):

    python -m src.m3.crosscheck sample --m2-dir M2_OUT --corpus-dir data/corpus \
        --labels-dir labels --sheet crosscheck_sheet.csv --key crosscheck_key.csv

   ``crosscheck_sheet.csv`` holds the entry and its top candidates (ordered by title
   similarity, numbered) but **not** the first label. The reviewer fills the column
   ``reviewer_choice`` with a candidate number, or 0 when none is correct. The first labels
   stay in ``crosscheck_key.csv``; do not open it before the sheet is filled.

2. Score:

    python -m src.m3.crosscheck score --sheet crosscheck_sheet.csv --key crosscheck_key.csv

   Prints the agreement rate per labeler and overall, and lists every disagreement so the
   two people can settle it (and fix the label file if the first label was wrong).
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

from src.m3.cleaning import entry_mentions_arxiv_id
from src.m3.labels import (
    author_overlap,
    iter_label_files,
    load_bibtex,
    load_candidates,
    range_owner,
    read_matrix,
    title_sim,
)


def _rank_for_review(entry: dict, candidates: list[dict]) -> list[dict]:
    """Order candidates for blind review using explicit arXiv ID, title and author signals."""
    return sorted(
        candidates,
        key=lambda c: (
            -int(entry_mentions_arxiv_id(entry, c["ref_arxiv_id"])),
            -max(
                title_sim(entry.get("title"), c["ref_title"]),
                author_overlap(entry.get("authors"), c["ref_authors"]),
            ),
            -title_sim(entry.get("title"), c["ref_title"]),
            -author_overlap(entry.get("authors"), c["ref_authors"]),
        ),
    )


SHEET = [
    "item",
    "labeler",
    "arxiv_id",
    "citation_key",
    "title",
    "authors",
    "year",
    "journal",
    "doi_url",
    "candidates",
    "reviewer_choice",
    "reviewer",
]


def sample(a) -> None:
    rng = random.Random(a.seed)
    files = list(iter_label_files(a.labels_dir, "manual"))
    pool: dict[str, list[tuple]] = defaultdict(list)
    matrices = {}
    for _, pid, path in files:
        cand_ids, answers = read_matrix(path)
        matrices[pid] = cand_ids
        for key, truth in answers.items():
            pool[range_owner(pid) or "unknown"].append((pid, key, truth))
    picked = []
    for labeler in sorted(pool):
        items = sorted(pool[labeler])
        picked += [(labeler, *x) for x in rng.sample(items, min(a.per_labeler, len(items)))]
    entries = {
        (e["arxiv_id"], e["citation_key"]): e for e in load_bibtex(a.m2_dir, {p[1] for p in picked})
    }

    sheet, key_rows = [], []
    for n, (labeler, pid, key, truth) in enumerate(picked, start=1):
        e = entries.get((pid, key), {"citation_key": key})
        cands = [
            c for c in load_candidates(a.corpus_dir, pid) if c["ref_arxiv_id"] in set(matrices[pid])
        ]
        ordered = _rank_for_review(e, cands)[: a.show]
        if truth and truth not in {c["ref_arxiv_id"] for c in ordered}:
            # keep the first label's choice reachable, at its review-rank position
            ordered = _rank_for_review(
                e, ordered + [c for c in cands if c["ref_arxiv_id"] == truth]
            )
        listing = "\n".join(
            f"{i}) {c['ref_arxiv_id']} | {c['ref_title']}" for i, c in enumerate(ordered, 1)
        )
        sheet.append(
            {
                "item": n,
                "labeler": labeler,
                "arxiv_id": pid,
                "citation_key": key,
                "title": e.get("title"),
                "authors": "; ".join(e.get("authors") or []),
                "year": e.get("year"),
                "journal": e.get("journal"),
                "doi_url": " ".join(filter(None, [e.get("doi"), e.get("url")])),
                "candidates": listing,
                "reviewer_choice": "",
                "reviewer": "",
            }
        )
        key_rows.append(
            {
                "item": n,
                "first_label": truth or "",
                "choices": "|".join(c["ref_arxiv_id"] for c in ordered),
            }
        )
    _write(a.sheet, SHEET, sheet)
    _write(a.key, ["item", "first_label", "choices"], key_rows)
    counts = ", ".join(f"{k}={min(a.per_labeler, len(v))}" for k, v in sorted(pool.items()))
    print(f"{len(sheet)} items ({counts}) -> {a.sheet}")


def score(a) -> dict:
    sheet = {r["item"]: r for r in _read(a.sheet)}
    key = {r["item"]: r for r in _read(a.key)}
    agree, total = defaultdict(int), defaultdict(int)
    disagreements = []
    for item, r in sheet.items():
        choice = r["reviewer_choice"].strip()
        if not choice.isdigit():
            print(f"item {item}: reviewer_choice missing, skipped")
            continue
        choices = key[item]["choices"].split("|") if key[item]["choices"] else []
        if int(choice) > len(choices):
            raise SystemExit(f"item {item}: choice {choice} but only {len(choices)} candidates")
        reviewer = "" if choice == "0" else choices[int(choice) - 1]
        first = key[item]["first_label"]
        total[r["labeler"]] += 1
        if reviewer == first:
            agree[r["labeler"]] += 1
        else:
            disagreements.append(
                (
                    item,
                    r["labeler"],
                    r["arxiv_id"],
                    r["citation_key"],
                    first or "none",
                    reviewer or "none",
                )
            )
    for labeler in sorted(total):
        k, n = agree[labeler], total[labeler]
        print(f"{labeler:<8} {k}/{n} = {k / n:.0%}")
    n, k = sum(total.values()), sum(agree.values())
    print(f"overall  {k}/{n} = {k / n:.0%}" if n else "no scored items")
    for d in disagreements:
        print("  disagree item {} ({}) {} {}: first={} reviewer={}".format(*d))
    return {"agree": k, "total": n, "disagreements": disagreements}


def _write(path: Path, fields, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # -sig: opens cleanly in Excel
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--m2-dir", type=Path, required=True)
    s.add_argument("--corpus-dir", type=Path, required=True)
    s.add_argument("--labels-dir", type=Path, default=Path("labels"))
    s.add_argument("--per-labeler", type=int, default=10)
    s.add_argument("--show", type=int, default=20)
    s.add_argument("--seed", type=int, default=20261118)
    for q in (s, sub.add_parser("score")):
        q.add_argument("--sheet", type=Path, default=Path("crosscheck_sheet.csv"))
        q.add_argument("--key", type=Path, default=Path("crosscheck_key.csv"))
    a = p.parse_args(argv)
    sample(a) if a.cmd == "sample" else score(a)


if __name__ == "__main__":
    main()
