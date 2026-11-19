# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Pick the papers each member labels by hand (default 5 per range, 20 in total).

    python -m src.m3.select_papers --m2-dir M2_OUT --corpus-dir data/corpus --out selection.csv

A paper is eligible when it has at least ``--min-entries`` BibTeX entries (statement: 20),
at least ``--min-candidates`` candidates and at least ``--min-hits`` entries whose normalized
that correct candidates exist, it is **not** a label. To cover several citation styles,
eligible papers of a range are split by the share of entries that carry a DOI or URL
(low / mid / high) and drawn round-robin from the three groups with a fixed seed.
Output: one row per chosen paper.
drawn round-robin from the three groups with a fixed seed. Output: one row per chosen paper.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

from src.config import RANGES
from src.m3.labels import load_bibtex, load_candidates, norm_text, range_owner

FIELDS = ["range_owner", "arxiv_id", "n_entries", "n_candidates", "n_title_hits", "share_doi_url"]


def paper_stats(entries: list[dict], candidates: list[dict]) -> dict:
    titles = {norm_text(c["ref_title"]) for c in candidates} - {""}
    hits = sum(1 for e in entries if norm_text(e.get("title")) in titles)
    with_link = sum(1 for e in entries if e.get("doi") or e.get("url"))
    return {
        "n_entries": len(entries),
        "n_candidates": len(candidates),
        "n_title_hits": hits,
        "share_doi_url": round(with_link / len(entries), 3) if entries else 0.0,
    }


def pick(rows: list[dict], k: int, rng: random.Random) -> list[dict]:
    """k rows drawn round-robin from the low/mid/high DOI-URL thirds."""
    rows = sorted(rows, key=lambda r: (r["share_doi_url"], r["arxiv_id"]))
    n = len(rows)
    groups = [rows[: n // 3], rows[n // 3 : 2 * n // 3], rows[2 * n // 3 :]]
    for g in groups:
        rng.shuffle(g)
    out = []
    while len(out) < k and any(groups):
        for g in groups:
            if g and len(out) < k:
                out.append(g.pop())
    return out


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--m2-dir", type=Path, required=True)
    p.add_argument("--corpus-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("selection.csv"))
    p.add_argument("--per-range", type=int, default=5)
    p.add_argument("--min-entries", type=int, default=20)
    p.add_argument("--min-candidates", type=int, default=20)
    p.add_argument("--min-hits", type=int, default=5)
    p.add_argument("--max-entries", type=int, default=80, help="keeps hand labeling feasible")
    p.add_argument("--seed", type=int, default=20261116)
    a = p.parse_args(argv)

    # only two light columns of the whole bibtex table are read to count entries per paper
    counts: dict[str, int] = defaultdict(int)
    for row in load_bibtex(a.m2_dir, columns=["arxiv_id"]):
        counts[row["arxiv_id"]] += 1
    shortlist = [
        pid for pid, n in counts.items() if a.min_entries <= n <= a.max_entries and range_owner(pid)
    ]
    print(f"{len(shortlist)} papers with {a.min_entries}-{a.max_entries} entries in the 4 ranges")

    rng = random.Random(a.seed)
    chosen = []
    by_range: dict[str, list[dict]] = defaultdict(list)
    for owner in RANGES:  # one range at a time keeps RAM bounded
        ids = [pid for pid in shortlist if range_owner(pid) == owner]
        entries_by_paper: dict[str, list[dict]] = defaultdict(list)
        for row in (
            load_bibtex(a.m2_dir, ids, columns=["arxiv_id", "title", "doi", "url"]) if ids else []
        ):
            entries_by_paper[row["arxiv_id"]].append(row)
        for pid in sorted(ids):
            cands = load_candidates(a.corpus_dir, pid)
            if len(cands) < a.min_candidates:
                continue
            stats = paper_stats(entries_by_paper[pid], cands)
            if stats["n_title_hits"] >= a.min_hits:
                by_range[owner].append({"range_owner": owner, "arxiv_id": pid, **stats})
        got = pick(by_range[owner], a.per_range, rng)
        print(f"{owner}: {len(by_range[owner])} eligible, {len(got)} chosen")
        if len(got) < a.per_range:
            print(
                f"  WARNING: {owner} has fewer than {a.per_range}; relax --min-hits/--max-entries"
            )
        chosen += got

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(chosen)
    print(f"{len(chosen)} papers, {sum(r['n_entries'] for r in chosen)} entries -> {a.out}")


if __name__ == "__main__":
    main()
