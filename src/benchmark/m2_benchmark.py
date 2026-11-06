# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Benchmark of the M2 parser: wall time, RAM and output size of one full run.

    python -m src.benchmark.m2_benchmark --data-root data/corpus --out-dir data/m2 \\
        --work-dir work/m2 --report bench_m2 -- --workers 2

Everything after ``--`` goes to ``python -m src.parser.run``. The run is started as a child
process and sampled from outside every ``--interval`` seconds: the resident memory (RSS) of the
child and all its descendants (the worker processes), and the size of the output folder. The
statement asks for "end-to-end wall time and average time per publication" and for "maximum RAM
and final output storage size"; the files written to ``--report`` carry exactly those:

- ``m2_benchmark_summary.csv`` (``metric,value,unit,tool``): ``wall_time_e2e``,
  ``time_per_paper`` (wall / papers of the corpus), ``ram_max``, ``ram_mean``, ``disk_max``,
  ``output_size``, plus the number of papers, versions and rows;
- ``m2_resource_timeseries.csv`` (``t_sec,rss_total_mb,disk_mb``);
- ``m2_papers.csv`` / ``m2_versions.csv`` copied from the runner's work directory.

Peaks are observed peaks of a sampler, so a spike shorter than the interval can be missed. The
numbers describe the machine they ran on; the official benchmark is run on a Colab CPU runtime
and the environment is recorded in ``environment.json``.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil


def tree_rss(proc: psutil.Process) -> int:
    """RSS in bytes of ``proc`` and all its descendants."""
    total = 0
    try:
        procs = [proc, *proc.children(recursive=True)]
    except psutil.Error:
        return 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            continue
    return total


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def benchmark(run_args: list[str], out_dir: Path, report: Path, interval: float = 0.5) -> dict:
    report.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "src.parser.run", *run_args]
    samples: list[tuple[float, float, float]] = []
    start = time.perf_counter()
    child = subprocess.Popen(cmd)
    watched = psutil.Process(child.pid)
    while child.poll() is None:
        samples.append(
            (
                time.perf_counter() - start,
                tree_rss(watched) / 1e6,
                folder_size(out_dir) / 1e6,
            )
        )
        time.sleep(interval)
    wall = time.perf_counter() - start
    samples.append((wall, 0.0, folder_size(out_dir) / 1e6))
    return {"cmd": cmd, "returncode": child.returncode, "wall": wall, "samples": samples}


def summarize(result: dict, work_dir: Path, out_dir: Path) -> list[dict]:
    rss = [s[1] for s in result["samples"] if s[1] > 0]
    papers = versions = 0
    papers_csv, versions_csv = work_dir / "m2_papers.csv", work_dir / "m2_versions.csv"
    if papers_csv.exists():
        with open(papers_csv, encoding="utf-8", newline="") as fh:
            papers = sum(1 for _ in csv.DictReader(fh))
    if versions_csv.exists():
        with open(versions_csv, encoding="utf-8", newline="") as fh:
            versions = sum(1 for _ in csv.DictReader(fh))
    size = folder_size(out_dir) / 1e6
    wall = result["wall"]
    rows = [
        ("wall_time_e2e", round(wall, 2), "s", "perf_counter"),
        ("time_per_paper", round(wall / papers, 4) if papers else "", "s", "wall / papers"),
        ("ram_max", round(max(rss, default=0), 1), "MB", "psutil RSS of the process tree"),
        ("ram_mean", round(sum(rss) / len(rss), 1) if rss else "", "MB", "psutil RSS, mean"),
        ("disk_max", round(max((s[2] for s in result["samples"]), default=0), 1), "MB", "du"),
        ("output_size", round(size, 2), "MB", "du of the Parquet shards"),
        ("papers", papers, "papers", "m2_papers.csv"),
        ("versions", versions, "versions", "m2_versions.csv"),
    ]
    return [dict(zip(("metric", "value", "unit", "tool"), r, strict=True)) for r in rows]


def write_report(result: dict, report: Path, work_dir: Path, out_dir: Path) -> None:
    rows = summarize(result, work_dir, out_dir)
    with open(report / "m2_benchmark_summary.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["metric", "value", "unit", "tool"])
        writer.writeheader()
        writer.writerows(rows)
    with open(report / "m2_resource_timeseries.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["t_sec", "rss_total_mb", "disk_mb"])
        for t, rss, disk in result["samples"]:
            writer.writerow([round(t, 2), round(rss, 1), round(disk, 2)])
    for name in ("m2_papers.csv", "m2_versions.csv"):
        if (work_dir / name).exists():
            shutil.copy2(work_dir / name, report / name)
    env = {
        "command": result["cmd"],
        "returncode": result["returncode"],
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": psutil.cpu_count(),
        "ram_total_mb": round(psutil.virtual_memory().total / 1e6),
    }
    (report / "environment.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ours, _, passed = (
        (argv[: argv.index("--")], "--", argv[argv.index("--") + 1 :])
        if "--" in argv
        else (argv, "", [])
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--crawl-work-dir", type=Path)
    parser.add_argument("--report", type=Path, default=Path("bench_m2"))
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args(ours)
    run_args = [
        "--data-root", str(args.data_root), "--out-dir", str(args.out_dir),
        "--work-dir", str(args.work_dir), "--no-progress",
    ]  # fmt: skip
    if args.crawl_work_dir:
        run_args += ["--crawl-work-dir", str(args.crawl_work_dir)]
    result = benchmark([*run_args, *passed], args.out_dir, args.report, args.interval)
    write_report(result, args.report, args.work_dir, args.out_dir)
    print(f"wall {result['wall']:.1f} s; report in {args.report}")
    return result["returncode"]


if __name__ == "__main__":
    sys.exit(main())
