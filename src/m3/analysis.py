# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Data analysis behind the feature choice and the poster numbers.

    python -m src.m3.analysis --m2-dir M2_OUT --corpus-dir data/corpus --labels-dir labels \
        --partitions partitions.csv --out-dir analysis/

Reads the label matrices and, for every (BibTeX entry, candidate) cell, computes the raw
signals the features are built on: title similarity, author last-name overlap, year
difference, exact DOI/arXiv-ID hit in the entry. Writes

    pairs.csv        one row per cell: method, arxiv_id, citation_key, ref_arxiv_id, label, signals
    signal_summary.csv  per signal and label (yes/no): count, mean, quartiles
    paper_summary.csv   per paper: entries, candidates, share of entries with no correct reference
    summary.txt         the headline numbers, readable as is

With ``--partitions`` (CSV ``arxiv_id,partition``) only Train papers are used, so Valid and
Test never influence the feature choice (no leakage, plan rule).
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pandas as pd

from src.m3.labels import (
    author_overlap,
    iter_label_files,
    load_bibtex,
    load_candidates,
    read_matrix,
    ref_year,
    title_sim,
)

SIGNALS = ["title_sim", "author_overlap", "year_diff", "id_in_entry"]


def id_in_entry(entry: dict, ref_arxiv_id: str) -> int:
    """1 when the candidate's arXiv ID appears in the entry's DOI/URL/journal text."""
    text = " ".join(str(entry.get(k) or "") for k in ("doi", "url", "journal")).lower()
    return int(
        bool(ref_arxiv_id)
        and re.search(rf"(?<![\d.]){re.escape(ref_arxiv_id.lower())}(?!\d)", text) is not None
    )


def pair_rows(method, arxiv_id, entries, candidates, answers):
    by_key = {e["citation_key"]: e for e in entries}
    by_id = {c["ref_arxiv_id"]: c for c in candidates}
    for key, truth in answers.items():
        e = by_key.get(key)
        if e is None:
            continue  # entry no longer in M2 output; reported in the summary as missing
        for ref_id, c in by_id.items():
            y = ref_year(c)
            yield {
                "method": method,
                "arxiv_id": arxiv_id,
                "citation_key": key,
                "ref_arxiv_id": ref_id,
                "label": "yes" if ref_id == truth else "no",
                "title_sim": round(title_sim(e.get("title"), c["ref_title"]), 4),
                "author_overlap": round(author_overlap(e.get("authors"), c["ref_authors"]), 4),
                "year_diff": abs(e["year"] - y) if e.get("year") and y else None,
                "id_in_entry": id_in_entry(e, ref_id),
            }


def summarize(pairs: pd.DataFrame, papers: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    rows = []
    for sig in SIGNALS:
        for label, g in pairs.groupby("label"):
            s = g[sig].dropna()
            rows.append(
                {
                    "signal": sig,
                    "label": label,
                    "count": len(s),
                    "missing": int(g[sig].isna().sum()),
                    "mean": s.mean(),
                    "q25": s.quantile(0.25),
                    "median": s.median(),
                    "q75": s.quantile(0.75),
                }
            )
    sig = pd.DataFrame(rows).round(4)

    yes = pairs[pairs.label == "yes"]
    # rank of the correct candidate when sorting by title similarity alone: a baseline for MRR
    ranks = []
    for _, g in pairs.groupby(["arxiv_id", "citation_key"]):
        if (g.label == "yes").any():
            order = g.sort_values("title_sim", ascending=False).reset_index(drop=True)
            ranks.append(int(order.index[order.label == "yes"][0]) + 1)
    mrr5 = sum(1 / r for r in ranks if r <= 5) / len(ranks) if ranks else float("nan")
    n_entries = int(papers.n_entries.sum())
    n_none = int(papers.n_no_match.sum())
    methods = ", ".join(f"{m}={n}" for m, n in papers.method.value_counts().items())
    nc = papers.n_candidates
    lines = [
        f"papers labeled            : {len(papers)} ({methods})",
        f"BibTeX entries labeled    : {n_entries}",
        f"entries with no correct ref: {n_none} ({n_none / max(n_entries, 1):.1%})",
        f"candidates per paper      : median {nc.median():.0f}, min {nc.min()}, max {nc.max()}",
        f"candidate cells (yes / no): {len(yes)} / {len(pairs) - len(yes)}",
        f"title_sim baseline MRR@5  : {mrr5:.4f} on {len(ranks)} entries with a correct ref",
        f"correct ref ranked 1 by title_sim: {sum(r == 1 for r in ranks) / max(len(ranks), 1):.1%}",
        "",
        "signal means, yes vs no:",
    ]
    for s in SIGNALS:
        m = sig[sig.signal == s].set_index("label")["mean"]
        lines.append(
            f"  {s:<15} yes {m.get('yes', float('nan')):.3f}   no {m.get('no', float('nan')):.3f}"
        )
    return sig, "\n".join(lines)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--m2-dir", type=Path, required=True)
    p.add_argument("--corpus-dir", type=Path, required=True)
    p.add_argument("--labels-dir", type=Path, default=Path("labels"))
    p.add_argument("--partitions", type=Path, help="CSV arxiv_id,partition: keep only train")
    p.add_argument("--method", choices=["manual", "auto"], help="default: both")
    p.add_argument("--out-dir", type=Path, default=Path("analysis"))
    a = p.parse_args(argv)

    files = list(iter_label_files(a.labels_dir, a.method))
    if a.partitions:
        with a.partitions.open(newline="", encoding="utf-8") as f:
            train = {r["arxiv_id"] for r in csv.DictReader(f) if r["partition"].lower() == "train"}
        files = [x for x in files if x[1] in train]
    if not files:
        raise SystemExit("no label files to analyse")

    entries_by_paper: dict[str, list[dict]] = {}
    for row in load_bibtex(a.m2_dir, [pid for _, pid, _ in files]):
        entries_by_paper.setdefault(row["arxiv_id"], []).append(row)

    pairs, papers = [], []
    for method, pid, path in files:
        cand_ids, answers = read_matrix(path)
        cands = [
            c for c in load_candidates(a.corpus_dir, pid) if c["ref_arxiv_id"] in set(cand_ids)
        ]
        entries = entries_by_paper.get(pid, [])
        pairs += pair_rows(method, pid, entries, cands, answers)
        known = {e["citation_key"] for e in entries}
        papers.append(
            {
                "method": method,
                "arxiv_id": pid,
                "n_entries": len(answers),
                "n_candidates": len(cand_ids),
                "n_no_match": sum(v is None for v in answers.values()),
                "n_missing_in_m2": sum(k not in known for k in answers),
            }
        )
    pairs_df, papers_df = pd.DataFrame(pairs), pd.DataFrame(papers)
    sig, text = summarize(pairs_df, papers_df)

    a.out_dir.mkdir(parents=True, exist_ok=True)
    pairs_df.to_csv(a.out_dir / "pairs.csv", index=False)
    sig.to_csv(a.out_dir / "signal_summary.csv", index=False)
    papers_df.to_csv(a.out_dir / "paper_summary.csv", index=False)
    (a.out_dir / "summary.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
