# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Copy only what M3 reads from Drive: M2 ``bibtex.parquet`` shards and M1 ``references.json``.

The full M1 restore (``src.benchmark.m2_restore``) copies every source file; M3 needs one
small JSON per paper, so this copies just those, verified against the SHA-256 recorded in
each M1 run's ``INDEX.json`` (with the ``.checkpoint-objects`` fallback of the Drive mirror).
The M1 runs are the ones listed in the M2 run's ``M2_MANIFEST.json``. Files already present
with the right hash are reused, so the cell can be re-run after a disconnect.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _copy_verified(sources: list[Path], dest: Path, expected: str) -> str:
    if dest.is_file() and _sha(dest) == expected:
        return "reused"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{uuid.uuid4().hex}.part")
    try:
        for src in sources:
            try:
                shutil.copyfile(src, tmp)
            except OSError:
                continue
            if _sha(tmp) == expected:
                os.replace(tmp, dest)
                return "copied"
        raise ValueError(f"no copy matches the indexed hash: {dest.name} ({sources[0]})")
    finally:
        tmp.unlink(missing_ok=True)


def restore_m1_json(
    m2_run_dir: Path,
    m1_drive_dir: Path,
    corpus_dir: Path,
    filenames: tuple[str, ...] = ("metadata.json", "references.json"),
    workers: int = 32,  # Drive reads are latency-bound: 8 -> ~6 files/s, 32 -> ~11 files/s on Colab
    on_progress=None,
) -> dict[str, int]:
    """Copy indexed M1 JSON files (e.g. ``metadata.json``, ``references.json``) with SHA-256."""
    wanted = set(filenames)
    manifest = json.loads((Path(m2_run_dir) / "M2_MANIFEST.json").read_text(encoding="utf-8"))
    jobs = []
    for rel in manifest["runs"].values():
        remote = Path(m1_drive_dir) / rel
        index = json.loads((remote / "INDEX.json").read_text(encoding="utf-8"))
        for name, sha in index["files"].items():
            parts = name.split("/")
            if len(parts) == 4 and parts[:2] == ["data", "corpus"] and parts[3] in wanted:
                backup = remote / ".checkpoint-objects" / sha[:2] / sha
                jobs.append(([remote / name, backup], Path(corpus_dir) / parts[2] / parts[3], sha))
    counts = {"copied": 0, "reused": 0, "total": len(jobs)}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, status in enumerate(pool.map(lambda j: _copy_verified(*j), jobs), start=1):
            counts[status] += 1
            if on_progress:
                on_progress(done, len(jobs))
    return counts


def restore_references(
    m2_run_dir: Path, m1_drive_dir: Path, corpus_dir: Path, workers=32, on_progress=None
):
    """Copy every indexed ``data/corpus/<folder>/references.json`` into ``corpus_dir/<folder>/``."""
    return restore_m1_json(
        m2_run_dir,
        m1_drive_dir,
        corpus_dir,
        filenames=("references.json",),
        workers=workers,
        on_progress=on_progress,
    )


def restore_metadata(
    m2_run_dir: Path, m1_drive_dir: Path, corpus_dir: Path, workers=32, on_progress=None
):
    """Copy every indexed ``data/corpus/<folder>/metadata.json`` into ``corpus_dir/<folder>/``."""
    return restore_m1_json(
        m2_run_dir,
        m1_drive_dir,
        corpus_dir,
        filenames=("metadata.json",),
        workers=workers,
        on_progress=on_progress,
    )


def restore_bibtex(m2_run_dir: Path, local_out: Path, on_progress=None):
    """Copy ``out/shard-*/bibtex.parquet`` of the M2 run (the other two tables are not needed).

    shortcut: checked by size only, not by the shard hash manifest; use src.qa.qa_inputs when
    the copy itself must be audited.
    """
    shards = sorted((Path(m2_run_dir) / "out").glob("shard-*/bibtex.parquet"))
    if not shards:
        raise FileNotFoundError(f"no out/shard-*/bibtex.parquet under {m2_run_dir}")
    counts = {"copied": 0, "reused": 0, "total": len(shards)}
    for done, src in enumerate(shards, start=1):
        dest = Path(local_out) / src.parent.name / src.name
        if dest.is_file() and dest.stat().st_size == src.stat().st_size:
            counts["reused"] += 1
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            shutil.copyfile(src, tmp)
            os.replace(tmp, dest)
            counts["copied"] += 1
        if on_progress:
            on_progress(done, len(shards))
    return counts
