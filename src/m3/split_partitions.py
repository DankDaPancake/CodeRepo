# Drafted with the help of an AI assistant (Gemini, Google), cited per the course rules.
"""Deterministic Train / Valid / Test split for Milestone 3 labeled publications.

    python -m src.m3.split_partitions create --labels-dir labels --out partitions.csv
    python -m src.m3.split_partitions verify --labels-dir labels --partitions partitions.csv

Implements the Milestone 3 per-member split rule (k = 4 members in ``src.config.RANGES``):
- ``test``:  1 manual + 1 auto publication per member range (4 manual + 4 auto total).
- ``valid``: 1 manual + 1 auto publication per member range (4 manual + 4 auto total).
- ``train``: all remaining labeled publications (manual and auto).

Validates every label matrix via ``src.m3.labels.read_matrix``, refuses any overlap between
manual and auto pools, enforces the per-publication floor Q >= 20 labeled BibTeX entries for
manual papers, and refuses to overwrite an existing ``partitions.csv`` unless ``--overwrite``
is explicitly passed (protecting the frozen test split).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from src.config import RANGES
from src.m3.labels import iter_label_files, range_owner, read_matrix

PARTITIONS = ("train", "valid", "test")


def _load_selection_ids(selection_csv: Path | None) -> set[str]:
    if selection_csv is None or not Path(selection_csv).is_file():
        return set()
    out: set[str] = set()
    with Path(selection_csv).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = (row.get("arxiv_id") or "").strip()
            if pid:
                out.add(pid)
    return out


def _scan_labeled_pool(
    labels_dir: Path,
    *,
    selection_csv: Path | None = None,
    min_manual_entries: int = 20,
) -> tuple[dict[str, str], dict[str, int]]:
    """Return ``(method_by_pid, entries_by_pid)`` after validating every CSV label matrix."""
    manual_files = list(iter_label_files(labels_dir, "manual"))
    auto_files = list(iter_label_files(labels_dir, "auto"))

    manual_ids = {pid for _, pid, _ in manual_files}
    auto_ids = {pid for _, pid, _ in auto_files}
    selection_ids = _load_selection_ids(selection_csv)

    overlap = (manual_ids | selection_ids) & auto_ids
    if overlap:
        raise ValueError(
            f"{len(overlap)} paper(s) appear in both manual and auto pools: {sorted(overlap)[:5]}"
        )

    method_by_pid: dict[str, str] = {}
    entries_by_pid: dict[str, int] = {}
    under_floor: list[str] = []

    for method, pid, path in manual_files + auto_files:
        _, answers = read_matrix(path)
        n = len(answers)
        if method == "manual" and n < min_manual_entries:
            under_floor.append(f"{pid} ({n} < {min_manual_entries})")
        method_by_pid[pid] = method
        entries_by_pid[pid] = n

    if under_floor:
        raise ValueError(
            f"manual paper(s) below the Q={min_manual_entries} entry floor: "
            + ", ".join(under_floor[:5])
        )
    return method_by_pid, entries_by_pid


def create_partitions(
    labels_dir: Path,
    out_csv: Path,
    *,
    selection_csv: Path | None = None,
    test_per_range: int = 1,
    valid_per_range: int = 1,
    min_manual_entries: int = 20,
    seed: int = 20261116,
    overwrite: bool = False,
) -> dict:
    """Create ``partitions.csv`` and ``partitions_summary.json`` from ``labels/{manual,auto}``."""
    out_csv = Path(out_csv)
    if out_csv.exists() and not overwrite:
        raise FileExistsError(
            f"{out_csv} already exists; refusing to regenerate a frozen split without --overwrite"
        )

    method_by_pid, entries_by_pid = _scan_labeled_pool(
        Path(labels_dir),
        selection_csv=selection_csv,
        min_manual_entries=min_manual_entries,
    )

    by_group: dict[tuple[str, str], list[str]] = defaultdict(list)
    unassigned: list[str] = []
    for pid, method in sorted(method_by_pid.items()):
        owner = range_owner(pid)
        if owner is None:
            unassigned.append(pid)
            continue
        by_group[(owner, method)].append(pid)
    if unassigned:
        raise ValueError(f"labeled paper(s) outside config.RANGES: {unassigned[:5]}")

    needed = test_per_range + valid_per_range
    shortfalls: list[str] = []
    for owner in sorted(RANGES):
        for method in ("manual", "auto"):
            have = len(by_group[(owner, method)])
            if have < needed:
                shortfalls.append(f"{owner}/{method}: have {have}, need >= {needed}")
    if shortfalls:
        raise ValueError("not enough labeled papers to form split: " + "; ".join(shortfalls))

    rng = random.Random(seed)
    partition_by_pid: dict[str, str] = {}
    for owner in sorted(RANGES):
        for method in ("manual", "auto"):
            pids = list(by_group[(owner, method)])
            rng.shuffle(pids)
            for pid in pids[:test_per_range]:
                partition_by_pid[pid] = "test"
            for pid in pids[test_per_range : test_per_range + valid_per_range]:
                partition_by_pid[pid] = "valid"
            for pid in pids[test_per_range + valid_per_range :]:
                partition_by_pid[pid] = "train"

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_csv.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["arxiv_id", "partition"])
        w.writeheader()
        for pid in sorted(partition_by_pid):
            w.writerow({"arxiv_id": pid, "partition": partition_by_pid[pid]})
    tmp.replace(out_csv)

    summary = _build_summary(
        out_csv,
        partition_by_pid,
        method_by_pid,
        entries_by_pid,
        seed=seed,
        test_per_range=test_per_range,
        valid_per_range=valid_per_range,
    )
    summary_path = out_csv.with_name("partitions_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _build_summary(
    out_csv: Path,
    partition_by_pid: dict[str, str],
    method_by_pid: dict[str, str],
    entries_by_pid: dict[str, int],
    *,
    seed: int | None = None,
    test_per_range: int | None = None,
    valid_per_range: int | None = None,
) -> dict:
    counts_by_part = Counter(partition_by_pid.values())
    counts_by_part_method: Counter = Counter()
    counts_by_part_method_range: Counter = Counter()
    entries_by_part: Counter = Counter()

    test_papers = []
    valid_papers = []
    for pid, part in sorted(partition_by_pid.items()):
        method = method_by_pid[pid]
        owner = range_owner(pid) or "unknown"
        counts_by_part_method[f"{part}_{method}"] += 1
        counts_by_part_method_range[f"{part}/{method}/{owner}"] += 1
        entries_by_part[part] += entries_by_pid.get(pid, 0)
        rec = {
            "arxiv_id": pid,
            "method": method,
            "range_owner": owner,
            "n_entries": entries_by_pid.get(pid, 0),
        }
        if part == "test":
            test_papers.append(rec)
        elif part == "valid":
            valid_papers.append(rec)

    sha = hashlib.sha256(out_csv.read_bytes()).hexdigest()
    return {
        "partitions_csv": str(out_csv),
        "partitions_sha256": sha,
        "seed": seed,
        "test_per_range": test_per_range,
        "valid_per_range": valid_per_range,
        "total_papers": len(partition_by_pid),
        "papers_by_partition": dict(sorted(counts_by_part.items())),
        "papers_by_partition_and_method": dict(sorted(counts_by_part_method.items())),
        "papers_by_partition_method_range": dict(sorted(counts_by_part_method_range.items())),
        "entries_by_partition": dict(sorted(entries_by_part.items())),
        "test_papers": test_papers,
        "valid_papers": valid_papers,
    }


def verify_partitions(
    partitions_csv: Path,
    labels_dir: Path,
    *,
    selection_csv: Path | None = None,
    test_per_range: int = 1,
    valid_per_range: int = 1,
    min_manual_entries: int = 20,
) -> dict:
    """Verify an existing ``partitions.csv`` against ``labels/{manual,auto}`` and M3 split rules."""
    partitions_csv = Path(partitions_csv)
    method_by_pid, entries_by_pid = _scan_labeled_pool(
        Path(labels_dir),
        selection_csv=selection_csv,
        min_manual_entries=min_manual_entries,
    )

    partition_by_pid: dict[str, str] = {}
    with partitions_csv.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            pid = (row.get("arxiv_id") or "").strip()
            part = (row.get("partition") or "").strip().lower()
            if not pid or part not in PARTITIONS:
                raise ValueError(f"{partitions_csv}:{i}: invalid row {row!r}")
            if pid in partition_by_pid:
                raise ValueError(f"{partitions_csv}:{i}: duplicate arxiv_id {pid}")
            partition_by_pid[pid] = part

    missing_in_csv = sorted(set(method_by_pid) - set(partition_by_pid))
    extra_in_csv = sorted(set(partition_by_pid) - set(method_by_pid))
    if missing_in_csv or extra_in_csv:
        raise ValueError(
            f"partition/label mismatch: {len(missing_in_csv)} labeled missing in CSV "
            f"({missing_in_csv[:3]}), {len(extra_in_csv)} unlabeled in CSV ({extra_in_csv[:3]})"
        )

    counts: Counter = Counter()
    for pid, part in partition_by_pid.items():
        owner = range_owner(pid)
        if owner is None:
            raise ValueError(f"{pid} outside config.RANGES")
        counts[(part, method_by_pid[pid], owner)] += 1

    bad_counts: list[str] = []
    for owner in sorted(RANGES):
        for method in ("manual", "auto"):
            if counts[("test", method, owner)] != test_per_range:
                bad_counts.append(
                    f"test/{method}/{owner}={counts[('test', method, owner)]} != {test_per_range}"
                )
            if counts[("valid", method, owner)] != valid_per_range:
                bad_counts.append(
                    f"valid/{method}/{owner}={counts[('valid', method, owner)]} "
                    f"!= {valid_per_range}"
                )
    if bad_counts:
        raise ValueError("split does not match per-range quotas: " + "; ".join(bad_counts))

    return _build_summary(
        partitions_csv,
        partition_by_pid,
        method_by_pid,
        entries_by_pid,
        test_per_range=test_per_range,
        valid_per_range=valid_per_range,
    )


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="create partitions.csv and partitions_summary.json")
    c.add_argument("--labels-dir", type=Path, required=True)
    c.add_argument("--out", type=Path, default=Path("partitions.csv"))
    c.add_argument("--selection-csv", type=Path)
    c.add_argument("--test-per-range", type=int, default=1)
    c.add_argument("--valid-per-range", type=int, default=1)
    c.add_argument("--min-manual-entries", type=int, default=20)
    c.add_argument("--seed", type=int, default=20261116)
    c.add_argument("--overwrite", action="store_true")

    v = sub.add_parser("verify", help="verify an existing partitions.csv against labels/")
    v.add_argument("--labels-dir", type=Path, required=True)
    v.add_argument("--partitions", type=Path, required=True)
    v.add_argument("--selection-csv", type=Path)
    v.add_argument("--test-per-range", type=int, default=1)
    v.add_argument("--valid-per-range", type=int, default=1)
    v.add_argument("--min-manual-entries", type=int, default=20)

    a = p.parse_args(argv)
    if a.cmd == "create":
        summary = create_partitions(
            a.labels_dir,
            a.out,
            selection_csv=a.selection_csv,
            test_per_range=a.test_per_range,
            valid_per_range=a.valid_per_range,
            min_manual_entries=a.min_manual_entries,
            seed=a.seed,
            overwrite=a.overwrite,
        )
    else:
        summary = verify_partitions(
            a.partitions,
            a.labels_dir,
            selection_csv=a.selection_csv,
            test_per_range=a.test_per_range,
            valid_per_range=a.valid_per_range,
            min_manual_entries=a.min_manual_entries,
        )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
