# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Benchmark of the M2 parser: wall time, RAM and disk of a full run, over one or more sessions.

    python -m src.benchmark.m2_benchmark --data-root runs/a/corpus --data-root runs/b/corpus \\
        --out-dir data/m2 --work-dir work/m2 --report bench_m2 -- --workers 2 --expect-assigned

Everything after ``--`` goes to ``python -m src.parser.run``. The run is started as a child
process and sampled from outside every ``--interval`` seconds: the resident memory (RSS) of the
child and all its descendants (the worker processes), and the size of the local output
(``--out-dir`` and ``--work-dir``). The statement asks for "end-to-end wall time and average
time per publication" and for "maximum RAM and final output storage size"; the files written to
``--report`` carry exactly those:

- ``m2_benchmark_summary.csv`` (``metric,value,unit,tool``): ``wall_time_e2e`` (the sum of the
  sessions), ``time_per_paper`` (wall / publications of the corpus), ``ram_max``, ``ram_mean``,
  ``disk_max`` (input plus output), ``input_size``, ``output_size``, ``sessions`` and the number
  of publications and versions;
- ``m2_resource_timeseries.csv`` (``session_id,t_sec,rss_total_mb,disk_mb``): one block per session;
- ``m2_sessions.jsonl``: one line per invocation (start, wall, exit code, command): the
  statement allows a run in several sessions if the log of each is kept, and the report adds
  them up. **Run the same command with the same ``--report`` to resume.** The runner skips what
  is committed, so a resumed session only costs the work that was left;
- ``m2_papers.csv`` / ``m2_versions.csv`` copied from the runner's work directory.

Peaks are observed peaks of a sampler, so a spike shorter than the interval can be missed. The
numbers describe the machine they ran on; ``environment.json`` records it. Copying the corpus to
the local disk happens before the first session and is not part of the wall time.
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
from datetime import UTC, datetime
from pathlib import Path

import psutil

SUMMARY = "m2_benchmark_summary.csv"
SERIES = "m2_resource_timeseries.csv"
SESSIONS = "m2_sessions.jsonl"


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
    if not Path(path).exists():
        return 0
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())


def benchmark(
    run_args: list[str], local_dirs: list[Path], report: Path, interval: float = 0.5
) -> dict:
    """Run the parser once and sample it. ``local_dirs`` are the folders it writes."""
    report.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "src.parser.run", *run_args]
    samples: list[tuple[float, float, float]] = []
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    start = time.perf_counter()
    child = subprocess.Popen(cmd)
    watched = psutil.Process(child.pid)

    def local_mb() -> float:
        return sum(folder_size(d) for d in local_dirs) / 1e6

    while child.poll() is None:
        samples.append((time.perf_counter() - start, tree_rss(watched) / 1e6, local_mb()))
        time.sleep(interval)
    wall = time.perf_counter() - start
    samples.append((wall, 0.0, local_mb()))
    return {
        "cmd": cmd,
        "returncode": child.returncode,
        "wall": wall,
        "started_at": started_at,
        "samples": samples,
    }


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _read_sessions(report: Path) -> list[dict]:
    path = report / SESSIONS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def summarize(
    sessions: list[dict], series: list[dict], work_dir: Path, inputs: float
) -> list[dict]:
    """The rows of the summary CSV from every session so far."""
    papers = len(_read_csv(work_dir / "m2_papers.csv"))
    versions = len(_read_csv(work_dir / "m2_versions.csv"))
    wall = sum(s["wall_s"] for s in sessions)
    rss = [float(r["rss_total_mb"]) for r in series if float(r["rss_total_mb"]) > 0]
    local = max((float(r["disk_mb"]) for r in series), default=0.0)
    output = sessions[-1]["output_mb"] if sessions else 0.0
    rows = [
        ("wall_time_e2e", round(wall, 2), "s", "sum of the sessions, perf_counter"),
        ("time_per_paper", round(wall / papers, 4) if papers else "", "s", "wall / publications"),
        ("ram_max", round(max(rss, default=0), 1), "MB", "psutil RSS of the process tree"),
        ("ram_mean", round(sum(rss) / len(rss), 1) if rss else "", "MB", "mean of the samples"),
        ("input_size", round(inputs, 3), "MB", "du of the corpus read"),
        ("output_size", round(output, 2), "MB", "du of the Parquet shards"),
        ("disk_max", round(inputs + local, 3), "MB", "input + peak of output and work"),
        ("sessions", len(sessions), "sessions", SESSIONS),
        ("papers", papers, "papers", "m2_papers.csv"),
        ("versions", versions, "versions", "m2_versions.csv"),
    ]
    return [dict(zip(("metric", "value", "unit", "tool"), r, strict=True)) for r in rows]


def write_report(
    result: dict, report: Path, work_dir: Path, out_dir: Path, data_roots: list[Path]
) -> None:
    """Add this session to the report and rebuild the summary from all sessions."""
    sessions = _read_sessions(report)
    session_id = len(sessions) + 1
    output_mb = folder_size(out_dir) / 1e6
    sessions.append(
        {
            "session_id": session_id,
            "started_at": result["started_at"],
            "wall_s": round(result["wall"], 2),
            "returncode": result["returncode"],
            "output_mb": round(output_mb, 2),
            "command": result["cmd"],
        }
    )
    with open(report / SESSIONS, "w", encoding="utf-8", newline="\n") as fh:
        for s in sessions:
            fh.write(json.dumps(s) + "\n")

    series = _read_csv(report / SERIES)
    series += [
        {
            "session_id": session_id,
            "t_sec": round(t, 2),
            "rss_total_mb": round(rss, 1),
            "disk_mb": round(disk, 2),
        }
        for t, rss, disk in result["samples"]
    ]
    with open(report / SERIES, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["session_id", "t_sec", "rss_total_mb", "disk_mb"])
        writer.writeheader()
        writer.writerows(series)

    inputs = sum(folder_size(r) for r in data_roots) / 1e6
    with open(report / SUMMARY, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["metric", "value", "unit", "tool"])
        writer.writeheader()
        writer.writerows(summarize(sessions, series, work_dir, inputs))
    for name in ("m2_papers.csv", "m2_versions.csv"):
        if (work_dir / name).exists():
            shutil.copy2(work_dir / name, report / name)
    env = {
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
    parser.add_argument("--data-root", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--crawl-work-dir", type=Path, action="append")
    parser.add_argument("--report", type=Path, default=Path("bench_m2"))
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args(ours)
    run_args = ["--out-dir", str(args.out_dir), "--work-dir", str(args.work_dir), "--no-progress"]
    for root in args.data_root:
        run_args += ["--data-root", str(root)]
    for work in args.crawl_work_dir or []:
        run_args += ["--crawl-work-dir", str(work)]
    result = benchmark(
        [*run_args, *passed], [args.out_dir, args.work_dir], args.report, args.interval
    )
    write_report(result, args.report, args.work_dir, args.out_dir, args.data_root)
    print(f"wall {result['wall']:.1f} s; report in {args.report}")
    return result["returncode"]


if __name__ == "__main__":
    sys.exit(main())
