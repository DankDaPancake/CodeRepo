# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Keep a long M2 run alive across Colab sessions: copy its state to Drive, copy it back.

The parser writes to the local disk of the Colab runtime (fast, atomic renames). A runtime that
dies takes that disk with it, so the state needed to *resume* is copied to Drive as the run
goes: the committed shards, the journal ``shards.jsonl`` that says which papers they hold, the
statistics CSVs and the benchmark report (which keeps the log of every session).

Order matters and makes the copy safe to interrupt: every shard folder is copied under a
temporary name and renamed, the journal is copied **last**. The journal on Drive therefore never
mentions a shard that is not complete there, and a shard on Drive that the journal does not
mention is deleted by the runner on resume, like any unfinished shard.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

JOURNAL_FILES = (
    "m2_papers.csv",
    "m2_versions.csv",
    "run_summary.json",
    "runs.jsonl",
    "assigned_check.json",
    "run.log",
    "shards.jsonl",  # last: the commit record of everything above it
)
PART = ".part-"


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(PART + dst.name)
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _copy_shard(src: Path, dst_root: Path) -> None:
    dst_root.mkdir(parents=True, exist_ok=True)
    tmp = dst_root / (PART + src.name)
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp)
    os.replace(tmp, dst_root / src.name)


def sync_to_drive(out_dir: Path, work_dir: Path, report_dir: Path, remote: Path) -> dict:
    """Copy what is new from the local run to ``remote``; returns what was copied."""
    out_dir, work_dir, report_dir, remote = map(Path, (out_dir, work_dir, report_dir, remote))
    copied = {"shards": 0, "files": 0}
    for shard in sorted(out_dir.glob("shard-*")):
        if not (remote / "out" / shard.name).is_dir():
            _copy_shard(shard, remote / "out")
            copied["shards"] += 1
    for name in JOURNAL_FILES:
        src = work_dir / name
        if src.is_file():
            _copy_file(src, remote / "work" / name)
            copied["files"] += 1
    if report_dir.is_dir():
        for src in sorted(p for p in report_dir.rglob("*") if p.is_file()):
            _copy_file(src, remote / "report" / src.relative_to(report_dir))
            copied["files"] += 1
    return copied


def restore_from_drive(remote: Path, out_dir: Path, work_dir: Path, report_dir: Path) -> dict:
    """Put the state of an earlier session back on a fresh runtime; refuses to overwrite."""
    out_dir, work_dir, report_dir, remote = map(Path, (out_dir, work_dir, report_dir, remote))
    if not (remote / "work" / "shards.jsonl").is_file():
        raise FileNotFoundError(f"nothing to resume in {remote}: no work/shards.jsonl")
    if any(out_dir.glob("shard-*")) or (work_dir / "shards.jsonl").exists():
        raise FileExistsError("this runtime already holds a run; resume needs a fresh one")
    restored = {"shards": 0, "files": 0}
    for shard in sorted((remote / "out").glob("shard-*")):
        shutil.copytree(shard, out_dir / shard.name)
        restored["shards"] += 1
    for src in sorted(p for p in (remote / "work").iterdir() if p.is_file()):
        if not src.name.startswith(PART):
            _copy_file(src, work_dir / src.name)
            restored["files"] += 1
    if (remote / "report").is_dir():
        for src in sorted(p for p in (remote / "report").rglob("*") if p.is_file()):
            if not src.name.startswith(PART):
                _copy_file(src, report_dir / src.relative_to(remote / "report"))
                restored["files"] += 1
    return restored
