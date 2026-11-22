# Drafted with the help of an AI assistant (Gemini, Google), cited per the course rules.
"""Rule-based automatic labeler for Milestone 3 (classical heuristics, no LLM/pretrained models).

Subcommands:
    run       Label at least 10% of the publications outside the manual pool (stratified across
              all four ranges, fixed seed) and save one yes/no candidate matrix per paper under
              ``<labels-dir>/auto/<folder>.csv`` (compatible with ``src.m3.labels.read_matrix``).
    evaluate  Measure precision, recall, F1, specificity and exact-match accuracy of the exact
              same rule matcher against the manual ground-truth matrices.

Matching cascade (precision-first, at most one ``yes`` per BibTeX entry):
1. ``explicit_id``       Candidate's ``ref_arxiv_id`` appears in entry ``doi``/``url``/``journal``.
2. ``exact_title``       Normalized titles match exactly (non-trivial length) with supporting
                         author/year signal (or missing metadata) and no ambiguous duplicate.
3. ``high_title_author`` High title similarity + surname overlap + compatible year + clear margin
                         over the runner-up candidate.
4. ``very_high_title``   Near-identical long title + clear margin + non-contradicting authors.
Otherwise ``no_match`` (all-``no`` row).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from src.m3.candidates import iter_shard_papers
from src.m3.cleaning import (
    author_surname_overlap_min,
    clean_text,
    entry_mentions_arxiv_id,
    extract_author_surnames,
    parse_year,
    title_char_similarity,
    title_token_jaccard,
    title_tokens,
)
from src.m3.labels import (
    iter_label_files,
    label_path,
    load_bibtex,
    load_candidates,
    range_owner,
    read_matrix,
    write_matrix,
)


@dataclass(frozen=True)
class AutoLabelConfig:
    """Thresholds for the classical rule-based reference matcher."""

    min_exact_title_chars: int = 15
    min_exact_title_tokens: int = 3
    high_title_char_sim: float = 0.90
    high_title_token_jaccard: float = 0.85
    high_title_min_chars: int = 15
    high_title_min_author_overlap: float = 0.34
    high_title_max_year_diff: int = 3
    high_title_min_margin: float = 0.08
    very_high_title_sim: float = 0.95
    very_high_title_min_chars: int = 25
    very_high_title_min_tokens: int = 4
    very_high_title_min_margin: float = 0.10


DEFAULT_CONFIG = AutoLabelConfig()


def _score_candidate(entry: dict, cand: dict) -> dict:
    etitle = entry.get("title")
    ctitle = cand.get("ref_title")
    eclean, cclean = clean_text(etitle), clean_text(ctitle)
    char_sim = title_char_similarity(etitle, ctitle)
    tok_jac = title_token_jaccard(etitle, ctitle)
    e_surnames = extract_author_surnames(entry.get("authors"))
    c_surnames = extract_author_surnames(cand.get("ref_authors"))
    auth_ov = author_surname_overlap_min(entry.get("authors"), cand.get("ref_authors"))
    eyear = parse_year(entry.get("year"))
    cyear = parse_year(cand.get("ref_submission_date"))
    year_diff = abs(eyear - cyear) if eyear is not None and cyear is not None else None
    return {
        "ref_arxiv_id": cand["ref_arxiv_id"],
        "exact_title": bool(eclean and eclean == cclean),
        "title_len": min(len(eclean), len(cclean)),
        "title_tokens": min(len(title_tokens(etitle)), len(title_tokens(ctitle))),
        "char_sim": char_sim,
        "tok_jac": tok_jac,
        "title_score": max(char_sim, tok_jac),
        "has_both_authors": bool(e_surnames and c_surnames),
        "author_overlap": auth_ov,
        "year_diff": year_diff,
    }


def match_entry(
    entry: dict,
    candidates: list[dict],
    cfg: AutoLabelConfig = DEFAULT_CONFIG,
) -> tuple[str | None, str]:
    """Return ``(ref_arxiv_id_or_None, rule_name)`` for one BibTeX entry."""
    if not candidates:
        return None, "no_match"

    # Rule 1: explicit arXiv ID in doi/url/journal.
    id_hits = [
        c["ref_arxiv_id"] for c in candidates if entry_mentions_arxiv_id(entry, c["ref_arxiv_id"])
    ]
    if len(id_hits) == 1:
        return id_hits[0], "explicit_id"

    scored = [_score_candidate(entry, c) for c in candidates]
    scored.sort(
        key=lambda s: (
            s["exact_title"],
            round(s["title_score"], 6),
            round(s["author_overlap"], 6),
            -(s["year_diff"] if s["year_diff"] is not None else 99),
        ),
        reverse=True,
    )
    top = scored[0]
    second_title = scored[1]["title_score"] if len(scored) > 1 else 0.0
    margin = top["title_score"] - second_title

    # Rule 2: exact normalized title (non-trivial) with no competing exact duplicate.
    exact_hits = [s for s in scored if s["exact_title"]]
    if (
        len(exact_hits) == 1
        and top["title_len"] >= cfg.min_exact_title_chars
        and top["title_tokens"] >= cfg.min_exact_title_tokens
    ):
        year_ok = top["year_diff"] is None or top["year_diff"] <= cfg.high_title_max_year_diff
        author_ok = (not top["has_both_authors"]) or top["author_overlap"] > 0.0
        if author_ok and year_ok:
            return top["ref_arxiv_id"], "exact_title"

    # Rule 3: high title similarity + surname overlap + compatible year + clear margin.
    if (
        top["title_len"] >= cfg.high_title_min_chars
        and (
            top["char_sim"] >= cfg.high_title_char_sim
            or top["tok_jac"] >= cfg.high_title_token_jaccard
        )
        and top["author_overlap"] >= cfg.high_title_min_author_overlap
        and (top["year_diff"] is None or top["year_diff"] <= cfg.high_title_max_year_diff)
        and margin >= cfg.high_title_min_margin
    ):
        return top["ref_arxiv_id"], "high_title_author"

    # Rule 4: near-identical long title with clear margin and non-contradicting authors.
    if (
        top["char_sim"] >= cfg.very_high_title_sim
        and top["title_len"] >= cfg.very_high_title_min_chars
        and top["title_tokens"] >= cfg.very_high_title_min_tokens
        and margin >= cfg.very_high_title_min_margin
        and ((not top["has_both_authors"]) or top["author_overlap"] > 0.0)
        and (top["year_diff"] is None or top["year_diff"] <= cfg.high_title_max_year_diff)
    ):
        return top["ref_arxiv_id"], "very_high_title"

    return None, "no_match"


def label_paper_auto(
    entries: list[dict],
    candidates: list[dict],
    cfg: AutoLabelConfig = DEFAULT_CONFIG,
) -> tuple[dict[str, str | None], Counter]:
    """Label every BibTeX entry of one paper; returns ``(answers, rule_counts)``."""
    answers: dict[str, str | None] = {}
    rules: Counter = Counter()
    for entry in sorted(entries, key=lambda e: e["citation_key"]):
        ref_id, rule = match_entry(entry, candidates, cfg)
        answers[entry["citation_key"]] = ref_id
        rules[rule] += 1
    return answers, rules


def _load_manual_ids(labels_dir: Path, selection_csv: Path | None) -> set[str]:
    manual: set[str] = set()
    if (labels_dir / "manual").is_dir():
        for _, pid, _ in iter_label_files(labels_dir, "manual"):
            manual.add(pid)
    if selection_csv is not None and selection_csv.is_file():
        with selection_csv.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = (row.get("arxiv_id") or "").strip()
                if pid:
                    manual.add(pid)
    return manual


def select_auto_papers(
    eligible_by_range: dict[str, list[str]],
    *,
    total_remaining_papers: int,
    ratio: float = 0.10,
    min_papers: int = 0,
    min_per_range: int = 2,
    seed: int = 20261117,
) -> list[str]:
    """Pick a stratified deterministic sample >= ``max(ceil(ratio * remaining), min_papers)``."""
    rng = random.Random(seed)
    n_ranges = max(len(eligible_by_range), 1)
    target = max(math.ceil(ratio * total_remaining_papers), min_papers, min_per_range * n_ranges)

    pools = {owner: sorted(pids) for owner, pids in sorted(eligible_by_range.items())}
    for pids in pools.values():
        rng.shuffle(pids)

    chosen: list[str] = []
    # Round-robin across ranges so every member's range gets balanced coverage.
    while len(chosen) < target and any(pools.values()):
        for owner in sorted(pools):
            if pools[owner] and len(chosen) < target:
                chosen.append(pools[owner].pop())
    return sorted(chosen)


def run_auto_label(
    m2_dir: Path,
    labels_dir: Path,
    *,
    refs_dir: Path | None = None,
    corpus_dir: Path | None = None,
    selection_csv: Path | None = None,
    total_corpus_papers: int | None = None,
    ratio: float = 0.10,
    min_papers: int = 0,
    seed: int = 20261117,
    cfg: AutoLabelConfig = DEFAULT_CONFIG,
    overwrite: bool = False,
) -> dict:
    """Select >=10% of non-manual publications and write ``labels/auto/<folder>.csv`` matrices."""
    labels_dir = Path(labels_dir)
    manual_ids = _load_manual_ids(labels_dir, selection_csv)

    # Pass 1 (lightweight): discover all papers outside the manual pool that have entries & cands.
    eligible_by_range: dict[str, list[str]] = defaultdict(list)
    all_seen_non_manual: set[str] = set()
    for _, pid, entries, candidates in iter_shard_papers(
        m2_dir,
        refs_dir=refs_dir,
        corpus_dir=corpus_dir,
        columns=["arxiv_id", "citation_key"],
    ):
        if pid in manual_ids:
            continue
        owner = range_owner(pid)
        if owner is None:
            continue
        all_seen_non_manual.add(pid)
        if entries and candidates:
            eligible_by_range[owner].append(pid)

    remaining_pool = (
        max(total_corpus_papers - len(manual_ids), len(all_seen_non_manual))
        if total_corpus_papers is not None
        else len(all_seen_non_manual)
    )
    selected = select_auto_papers(
        eligible_by_range,
        total_remaining_papers=remaining_pool,
        ratio=ratio,
        min_papers=min_papers,
        min_per_range=2,
        seed=seed,
    )
    selected_set = set(selected)

    # Pass 2: stream only selected papers shard-by-shard and write label matrices.
    rule_totals: Counter = Counter()
    per_range: Counter = Counter()
    entries_total = 0
    matched_total = 0
    written_papers = 0
    skipped_existing = 0

    for _, pid, entries, candidates in iter_shard_papers(
        m2_dir,
        refs_dir=refs_dir,
        corpus_dir=corpus_dir,
        arxiv_ids=selected_set,
    ):
        dest = label_path(labels_dir, "auto", pid)
        cand_ids = [c["ref_arxiv_id"] for c in candidates]
        if dest.exists() and not overwrite:
            _, answers = read_matrix(dest)
            skipped_existing += 1
        else:
            answers, rules = label_paper_auto(entries, candidates, cfg)
            write_matrix(dest, cand_ids, answers)
            rule_totals.update(rules)
            written_papers += 1
        per_range[range_owner(pid) or "unknown"] += 1
        entries_total += len(answers)
        matched_total += sum(v is not None for v in answers.values())

    summary = {
        "manual_excluded": len(manual_ids),
        "remaining_pool": remaining_pool,
        "eligible_non_manual": sum(len(v) for v in eligible_by_range.values()),
        "selected_papers": len(selected),
        "selected_share_of_remaining": round(len(selected) / max(remaining_pool, 1), 4),
        "written_papers": written_papers,
        "skipped_existing": skipped_existing,
        "per_range": dict(sorted(per_range.items())),
        "entries_labeled": entries_total,
        "entries_matched": matched_total,
        "match_rate": round(matched_total / max(entries_total, 1), 4),
        "rule_counts": dict(sorted(rule_totals.items())),
        "seed": seed,
        "config": asdict(cfg),
    }
    labels_dir.mkdir(parents=True, exist_ok=True)
    (labels_dir / "auto_label_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def evaluate_on_manual(
    m2_dir: Path,
    labels_dir: Path,
    *,
    refs_dir: Path | None = None,
    corpus_dir: Path | None = None,
    partitions_csv: Path | None = None,
    partition_filter: str | None = None,
    out_dir: Path | None = None,
    cfg: AutoLabelConfig = DEFAULT_CONFIG,
) -> dict:
    """Evaluate the rule matcher against manual ground-truth CSVs in ``<labels-dir>/manual/``."""
    files = list(iter_label_files(labels_dir, "manual"))
    if partitions_csv is not None and partition_filter is not None:
        with Path(partitions_csv).open(newline="", encoding="utf-8") as f:
            keep = {
                r["arxiv_id"]
                for r in csv.DictReader(f)
                if r["partition"].strip().lower() == partition_filter.lower()
            }
        files = [x for x in files if x[1] in keep]
    if not files:
        raise SystemExit("no manual label files to evaluate")

    pids = [pid for _, pid, _ in files]
    entries_by_paper: dict[str, list[dict]] = defaultdict(list)
    for row in load_bibtex(m2_dir, pids):
        entries_by_paper[row["arxiv_id"]].append(row)

    cands_by_paper: dict[str, list[dict]] = {}
    if refs_dir is not None:
        from src.m3.candidates import _open_references_dataset, load_candidates_batch

        cands_by_paper = load_candidates_batch(
            pids, refs_dataset=_open_references_dataset(refs_dir)
        )
    elif corpus_dir is not None:
        cands_by_paper = {pid: load_candidates(corpus_dir, pid) for pid in pids}
    else:
        raise ValueError("provide either refs_dir or corpus_dir")

    exact_ok = 0
    tp = fp = fn = tn = wrong_id = 0
    total = 0
    by_rule: dict[str, Counter] = defaultdict(Counter)
    errors: list[dict] = []

    for _, pid, path in files:
        cand_ids, truth_map = read_matrix(path)
        cand_set = set(cand_ids)
        cands = [c for c in cands_by_paper.get(pid, []) if c["ref_arxiv_id"] in cand_set]
        entry_map = {e["citation_key"]: e for e in entries_by_paper.get(pid, [])}
        for key, truth in sorted(truth_map.items()):
            entry = entry_map.get(key)
            if entry is None:
                continue
            pred, rule = match_entry(entry, cands, cfg)
            total += 1
            if pred == truth:
                exact_ok += 1
                by_rule[rule]["correct"] += 1
                if truth is None:
                    tn += 1
                else:
                    tp += 1
            else:
                by_rule[rule]["wrong"] += 1
                if pred is not None and truth is None:
                    fp += 1
                elif pred is None and truth is not None:
                    fn += 1
                else:
                    # Predicted a match, but picked the wrong candidate ID (both FP and FN).
                    fp += 1
                    fn += 1
                    wrong_id += 1
                errors.append(
                    {
                        "arxiv_id": pid,
                        "citation_key": key,
                        "truth": truth or "",
                        "predicted": pred or "",
                        "rule": rule,
                        "entry_title": entry.get("title") or "",
                    }
                )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    specificity = tn / (tn + (fp - wrong_id)) if (tn + (fp - wrong_id)) else 0.0

    report = {
        "papers_evaluated": len(files),
        "entries_evaluated": total,
        "exact_accuracy": round(exact_ok / max(total, 1), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "wrong_id": wrong_id,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "no_match_specificity": round(specificity, 4),
        "by_rule": {r: dict(c) for r, c in sorted(by_rule.items())},
        "config": asdict(cfg),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "auto_eval_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with (out_dir / "auto_eval_errors.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "arxiv_id",
                    "citation_key",
                    "truth",
                    "predicted",
                    "rule",
                    "entry_title",
                ],
            )
            w.writeheader()
            w.writerows(errors)
    return report


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--m2-dir", type=Path, required=True)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--refs-dir", type=Path, help="exported references Parquet directory")
    src.add_argument("--corpus-dir", type=Path, help="M1 corpus directory with references.json")
    parser.add_argument("--labels-dir", type=Path, default=Path("labels"))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="generate auto-label matrices for >=10% of non-manual papers")
    _add_source_args(r)
    r.add_argument("--selection-csv", type=Path, help="manual selection.csv to exclude")
    r.add_argument(
        "--total-corpus-papers",
        type=int,
        default=20000,
        help="total assigned corpus size used to enforce the >=10%% floor (default: 20000)",
    )
    r.add_argument("--ratio", type=float, default=0.10)
    r.add_argument("--min-papers", type=int, default=2000)
    r.add_argument("--seed", type=int, default=20261117)
    r.add_argument("--overwrite", action="store_true")

    e = sub.add_parser("evaluate", help="measure auto-labeler accuracy on manual labels")
    _add_source_args(e)
    e.add_argument("--partitions", type=Path, help="optional partitions.csv")
    e.add_argument("--partition", choices=["train", "valid", "test"])
    e.add_argument("--out-dir", type=Path)

    a = p.parse_args(argv)
    if a.cmd == "run":
        result = run_auto_label(
            a.m2_dir,
            a.labels_dir,
            refs_dir=a.refs_dir,
            corpus_dir=a.corpus_dir,
            selection_csv=a.selection_csv,
            total_corpus_papers=a.total_corpus_papers,
            ratio=a.ratio,
            min_papers=a.min_papers,
            seed=a.seed,
            overwrite=a.overwrite,
        )
    else:
        result = evaluate_on_manual(
            a.m2_dir,
            a.labels_dir,
            refs_dir=a.refs_dir,
            corpus_dir=a.corpus_dir,
            partitions_csv=a.partitions,
            partition_filter=a.partition,
            out_dir=a.out_dir,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
