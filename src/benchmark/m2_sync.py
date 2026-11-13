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

import hashlib
import json
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
    "bbl-input-identity.json",
    "corpus-input-identity.json",
    "parser-config-identity.json",
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


def _tree_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Shard contains symlink: {path}")
        if path.is_file():
            with path.open("rb") as stream:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    return result


def sync_to_drive(
    out_dir: Path, work_dir: Path, report_dir: Path, remote: Path, *, include_report: bool = True
) -> dict:
    """Copy what is new from the local run to ``remote``; returns what was copied."""
    out_dir, work_dir, report_dir, remote = map(Path, (out_dir, work_dir, report_dir, remote))
    copied = {"shards": 0, "files": 0}
    journal = work_dir / "shards.jsonl"
    snapshot = journal.read_bytes() if journal.is_file() else b""
    if snapshot and not snapshot.endswith(b"\n"):
        snapshot = snapshot[: snapshot.rfind(b"\n") + 1]
    shard_ids = []
    for line in snapshot.splitlines():
        record = json.loads(line)
        shard_id = record["shard"]
        if not isinstance(shard_id, int) or isinstance(shard_id, bool) or shard_id < 0:
            raise ValueError("Invalid shard number in journal")
        shard_ids.append(shard_id)
    shard_hashes = {}
    for number in shard_ids:
        shard = out_dir / f"shard-{number:05d}"
        if not shard.is_dir():
            raise FileNotFoundError(f"Journal refers to missing shard: {shard}")
        if not (remote / "out" / shard.name).is_dir():
            _copy_shard(shard, remote / "out")
            copied["shards"] += 1
        shard_hashes[shard.name] = _tree_hashes(shard)
        if shard_hashes[shard.name] != _tree_hashes(remote / "out" / shard.name):
            raise ValueError(f"Shard integrity failure: {shard.name}")
    for name in JOURNAL_FILES:
        src = work_dir / name
        if src.is_file():
            _copy_file(src, remote / "work" / name)
            copied["files"] += 1
    if snapshot:
        target = remote / "work" / "shards.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        hashes = target.with_name("shard-hashes.json")
        temp_hashes = hashes.with_name(PART + hashes.name)
        temp_hashes.write_text(json.dumps(shard_hashes, sort_keys=True), encoding="utf8")
        os.replace(temp_hashes, hashes)
        temp = target.with_name(PART + target.name)
        temp.write_bytes(snapshot)
        os.replace(temp, target)
        copied["files"] += 1
    if include_report and report_dir.is_dir():
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
    hashes_file = remote / "work" / "shard-hashes.json"
    if not hashes_file.is_file():
        raise ValueError("Missing shard integrity manifest")
    hashes = json.loads(hashes_file.read_text(encoding="utf8"))
    journal = (remote / "work" / "shards.jsonl").read_text(encoding="utf8")
    for line in journal.splitlines():
        record = json.loads(line)
        number = record["shard"]
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ValueError("Invalid shard number in journal")
        name = f"shard-{number:05d}"
        shard = remote / "out" / name
        if name not in hashes or not shard.is_dir() or _tree_hashes(shard) != hashes[name]:
            raise ValueError(f"Shard integrity failure: {name}")
    restored = {"shards": 0, "files": 0}
    for shard in sorted((remote / "out").glob("shard-*")):
        shutil.copytree(shard, out_dir / shard.name)
        if shard.name in hashes and _tree_hashes(out_dir / shard.name) != hashes[shard.name]:
            raise ValueError(f"Shard integrity failure after restore: {shard.name}")
        restored["shards"] += 1
    for src in sorted(p for p in (remote / "work").iterdir() if p.is_file()):
        if not src.name.startswith(PART) and src.name not in {"shards.jsonl", "shard-hashes.json"}:
            _copy_file(src, work_dir / src.name)
            restored["files"] += 1
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "shard-hashes.json").write_text(json.dumps(hashes, sort_keys=True), encoding="utf8")
    (work_dir / "shards.jsonl").write_text(journal, encoding="utf8")
    restored["files"] += 2
    if (remote / "report").is_dir():
        for src in sorted(p for p in (remote / "report").rglob("*") if p.is_file()):
            if not src.name.startswith(PART):
                _copy_file(src, report_dir / src.relative_to(remote / "report"))
                restored["files"] += 1
    return restored
