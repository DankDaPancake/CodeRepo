"""One resumable full-crawl benchmark, used by the Colab entry notebook.

The parent profiles each child. Children checkpoint only at
completed-version boundaries, within the profiler's measured process tree.
"""

# Drafted with assistance from OpenAI Codex, disclosed per course rules.

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from tqdm.auto import tqdm

from src import config
from src.benchmark.checkpoints import Checkpoints, prepare_drive, write_json
from src.utils.ids import iter_id_range

GROUP_SNAPSHOT_HASHES = {
    "only_v1": "2cb0fa363ce57bfb63f668603c8a4e6e3d790fde47e7af1b482df5235d7ea175",
    "multi_version": "4d457f0e78bea5bae7addad0e56f55e056949b61037925fd0412ef20b0e5a081",
}


@dataclass(frozen=True)
class BenchmarkConfig:
    run_id: str
    mode: str = "final"
    ranges: tuple[str, ...] = ("thien", "tien", "hieu", "dang")
    offset: int = 0
    count: int | None = None
    chunk_size: int = 100
    references: bool = True
    checkpoint_s: float = 300.0
    snapshot: str | None = None
    storage_backend: str = "drive"
    hf_repo_id: str | None = None
    chunk_attempts: int = 3  # tries per chunk before it is recorded as incomplete
    chunk_cooldown_s: float = 300.0  # wait before try k+1 is k x this (arXiv 429 windows)
    adaptive_pacing: bool = False  # spec 0004: slow the pace after HTTP 429
    source_mode: str = "arxiv"
    s3_manifest: str | None = None
    s3_bundle_dir: str | None = None
    snapshot_group: str = "all"


@dataclass(frozen=True)
class Chunk:
    owner: str
    offset: int
    ids: tuple[str, ...]


def order_hybrid_chunks(chunks, partition):
    """Order all single-version chunks before any multi-version chunks."""
    if partition.missing:
        raise ValueError(f"Snapshot missing or invalid for {len(partition.missing)} IDs")
    all_ids = [pid for chunk in chunks for pid in chunk.ids]
    single, multi = set(partition.only_v1), set(partition.multi_version)
    if single & multi or single | multi != set(all_ids) or len(all_ids) != len(set(all_ids)):
        raise ValueError("Hybrid partition does not match selected IDs")
    phases = []
    for name, selected in (("only_v1", single), ("multi_version", multi)):
        for chunk in chunks:
            ids = tuple(pid for pid in chunk.ids if pid in selected)
            if ids:
                phases.append((name, Chunk(chunk.owner, chunk.offset, ids)))
    return phases


def prepare_s3_index(manifest_path: Path, directory: Path, ids: list[str]) -> dict:
    """Verify candidate bundles and index source members before the first S3 phase."""
    import tarfile

    from src.crawler.s3_prepare import _id, parse_manifest, select_bundles
    from src.crawler.s3_sources import index_verified_bundle

    bundles, _ = select_bundles(parse_manifest(manifest_path.read_bytes()), ids)
    index = {}
    errors = {}
    for bundle in bundles:
        path = directory / Path(bundle.key).name
        candidates = {pid for pid in ids if _id(bundle.first) <= _id(pid) <= _id(bundle.last)}
        if not path.is_file():
            print(f"S3 bundle missing; eligible IDs will fall back: {path.name}", flush=True)
            for pid in candidates:
                errors[pid] = {
                    "status": "bundle_error",
                    "reason": "bundle_missing",
                    "bundle": bundle.key,
                }
            continue
        try:
            found = index_verified_bundle(path, bundle, set(ids))
        except (OSError, ValueError, tarfile.TarError) as exc:
            print(f"S3 bundle failed; eligible IDs will fall back: {bundle.key}: {exc}", flush=True)
            for pid in candidates:
                errors[pid] = {"status": "bundle_error", "reason": str(exc), "bundle": bundle.key}
            continue
        for pid in set(found) & set(index):
            errors[pid] = {"status": "bundle_error", "reason": "duplicate paper across bundles"}
        for entry in found.values():
            entry.update(path=str(path), bundle_timestamp=bundle.timestamp)
        index.update(found)
    index.update(errors)
    for pid in set(ids) - index.keys():
        index[pid] = {"status": "source_missing"}
    return index


def plan_chunks(cfg: BenchmarkConfig) -> list[Chunk]:
    if cfg.snapshot_group not in ("all", "only_v1", "multi_version"):
        raise ValueError("Invalid snapshot group")
    if cfg.snapshot_group != "all" and (not cfg.snapshot or cfg.mode == "final"):
        raise ValueError("Snapshot groups require a snapshot and partition/sample mode")
    if cfg.source_mode not in ("arxiv", "s3", "arxiv_s3"):
        raise ValueError("Invalid source mode")
    if cfg.source_mode != "arxiv" and not (cfg.snapshot and cfg.s3_manifest and cfg.s3_bundle_dir):
        raise ValueError("S3 source requires snapshot, manifest and bundle directory")
    if cfg.storage_backend not in ("drive", "huggingface"):
        raise ValueError("Unknown storage backend")
    if cfg.storage_backend == "huggingface" and not cfg.hf_repo_id:
        raise ValueError("HF Dataset repo ID is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", cfg.run_id):
        raise ValueError("Run ID must be a simple unique name")
    if cfg.mode not in ("sample", "partition", "final") or cfg.chunk_size < 1 or cfg.offset < 0:
        raise ValueError("Invalid benchmark selection")
    if cfg.checkpoint_s <= 0 or (cfg.count is not None and cfg.count < 1):
        raise ValueError("Count and checkpoint interval must be positive")
    if cfg.chunk_attempts < 1 or cfg.chunk_cooldown_s < 0:
        raise ValueError("Chunk attempts must be >= 1 and the cooldown not negative")
    if (
        not cfg.ranges
        or len(set(cfg.ranges)) != len(cfg.ranges)
        or set(cfg.ranges) - config.RANGES.keys()
    ):
        raise ValueError("Invalid or duplicate ranges")
    if cfg.mode == "final" and (
        set(cfg.ranges) != set(config.RANGES)
        or cfg.offset
        or cfg.count is not None
        or not cfg.references
    ):
        raise ValueError("Final mode needs all four full ranges and references")
    chunks = []
    for owner in cfg.ranges:
        start, end = config.RANGES[owner]
        ids = list(iter_id_range(start, end, config.MONTH_END))[cfg.offset :]
        if cfg.count is not None:
            ids = ids[: cfg.count]
        if not ids:
            raise ValueError("Selection is empty")
        for pos in range(0, len(ids), cfg.chunk_size):
            chunks.append(Chunk(owner, cfg.offset + pos, tuple(ids[pos : pos + cfg.chunk_size])))
    if cfg.snapshot_group != "all":
        from src.crawler.s3_partition import partition_snapshot
        from src.crawler.snapshot import sha256

        all_ids = [pid for chunk in chunks for pid in chunk.ids]
        partition = partition_snapshot(Path(cfg.snapshot), all_ids)
        fingerprint = sha256(Path(cfg.snapshot))
        if (
            fingerprint in GROUP_SNAPSHOT_HASHES.values()
            and fingerprint != GROUP_SNAPSHOT_HASHES[cfg.snapshot_group]
        ):
            raise ValueError("Snapshot belongs to a different group")
        verified_subset = fingerprint == GROUP_SNAPSHOT_HASHES[cfg.snapshot_group]
        other = partition.multi_version if cfg.snapshot_group == "only_v1" else partition.only_v1
        if verified_subset and other:
            raise ValueError("Snapshot contains paper from the wrong group")
        if partition.missing and not verified_subset:
            raise ValueError(f"Snapshot missing or invalid for {len(partition.missing)} IDs")
        selected = set(getattr(partition, cfg.snapshot_group))
        chunks = [
            Chunk(chunk.owner, chunk.offset, tuple(pid for pid in chunk.ids if pid in selected))
            for chunk in chunks
        ]
        chunks = [chunk for chunk in chunks if chunk.ids]
        if not chunks:
            raise ValueError("Snapshot group selection is empty")
    return chunks


def prepare_run(cfg: BenchmarkConfig, root: Path, revision: str, *, resume: bool) -> dict:
    chunks = plan_chunks(cfg)
    config_data = asdict(cfg)
    if cfg.snapshot_group == "all":
        config_data.pop("snapshot_group")
    identity = {"config": json.loads(json.dumps(config_data)), "code_revision": revision}
    if cfg.snapshot:
        from src.crawler.snapshot import sha256

        identity["snapshot_sha256"] = sha256(Path(cfg.snapshot))
    if cfg.source_mode != "arxiv":
        identity["s3_manifest_sha256"] = sha256(Path(cfg.s3_manifest))
    path = root / cfg.run_id / "MANIFEST.json"
    if resume:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if any(manifest.get(k) != v for k, v in identity.items()):
            raise ValueError("Run configuration/code revision differs from the saved run")
        return manifest
    if (root / cfg.run_id).exists():
        raise FileExistsError("Run already exists; select resume or a new run ID")
    manifest = dict(
        identity,
        started_at=datetime.now(UTC).isoformat(),
        required_ids=[i for c in chunks for i in c.ids],
    )
    write_json(path, manifest)
    return manifest


def claim_hf_run(hub, run_id: str, manifest: dict) -> None:
    """Atomically reserve a new run name, without a global shift marker."""
    from huggingface_hub.errors import HfHubHTTPError

    path = f"runs/{run_id}/MANIFEST.json"
    for attempt in range(5):
        head = hub.get_head()
        if not head:
            raise ValueError("Initialize the HF Dataset repository before creating a run")
        if hub.read(path, revision=head, missing_ok=True) is not None:
            raise FileExistsError(f"HF run ID already exists: {run_id}")
        try:
            hub.commit({path: json.dumps(manifest).encode("utf-8")}, "M1 reserve run", parent=head)
            return
        except HfHubHTTPError as exc:
            if exc.response is None or exc.response.status_code != 409 or attempt == 4:
                raise
    raise RuntimeError("Could not reserve HF run")


def coverage(cfg: BenchmarkConfig, local: Path) -> dict:
    """QA over exact requested IDs, not just the most recent chunk."""
    from src.qa.validate import load_versions_log, validate_range, write_report

    ids = [i for c in plan_chunks(cfg) for i in c.ids]
    data, work = local / "data/corpus", local / "work"
    journal = work / "versions.jsonl"
    logs = load_versions_log(journal) if journal.exists() else {}
    source_issues, _ = validate_range(ids, data, owner="benchmark", versions_log=logs)
    ref_issues, _ = validate_range(
        ids, data, owner="benchmark", versions_log=logs, require_references=cfg.references
    )
    write_report(work / "qa_source.csv", source_issues)
    write_report(work / "qa_report.csv", ref_issues)
    source_bad = {i.arxiv_id for i in source_issues if i.severity == "error"}
    all_bad = {i.arxiv_id for i in ref_issues if i.severity == "error"}
    result = dict(
        mode=cfg.mode,
        required_ids=len(ids),
        unique_ids=len(set(ids)),
        papers_source_complete=len(ids) - len(source_bad),
        papers_with_reference_or_source_errors=len(all_bad),
        complete=not all_bad and len(ids) == len(set(ids)),
        final_complete=cfg.mode == "final" and len(ids) == 20_000 and not all_bad,
        source_mode=cfg.source_mode,
        s3_inferred_versions=sum(
            rec.get("version_evidence") == "inferred_snapshot_bundle_timestamp"
            for rec in logs.values()
        ),
    )
    write_json(work / "coverage.json", result)
    return result


def _chunk_complete(chunk: Chunk, local: Path, references: bool) -> bool:
    """Skip only chunks that pass the actual corpus/metadata/journal QA."""
    from src.qa.validate import load_versions_log, validate_range

    journal = local / "work/versions.jsonl"
    if not journal.exists():
        return False
    issues, _ = validate_range(
        list(chunk.ids),
        local / "data/corpus",
        owner=chunk.owner,
        versions_log=load_versions_log(journal),
        require_references=references,
    )
    return not any(i.severity == "error" for i in issues)


def checkpoint_backend(local, remote, *, repo_id=None, hub=None):
    if repo_id:
        from src.benchmark.huggingface import HFCheckpoints, HubStore

        hub = hub or HubStore(repo_id, remote.parent.parent / ".hf-cache")
        return HFCheckpoints(local, remote, hub, f"runs/{remote.name}")
    return Checkpoints(local, remote)


def forward_paper_progress(path: Path, offset: int, on_progress, on_version=None) -> int:
    """Read completed progress events without consuming partial lines."""
    with path.open("rb") as console:
        console.seek(offset)
        while True:
            start = console.tell()
            line = console.readline()
            if not line or not line.endswith(b"\n"):
                return start
            match = re.search(rb"PAPER_PROGRESS source_terminal=(\d+)/(\d+)", line)
            if match:
                count, total = map(int, match.groups())
                if count <= total:
                    on_progress(count, total)
            match = re.search(rb"VERSION_PROGRESS source_terminal=(\d+)/(\d+)", line)
            if match and on_version is not None:
                count, total = map(int, match.groups())
                if count <= total:
                    on_version(count, total)


def run_child(payload: dict) -> None:
    from src.run_pipeline import run

    local, remote = Path(payload["local"]), Path(payload["remote"])
    cp = checkpoint_backend(local, remote, repo_id=payload.get("hf_repo_id"))
    last = time.monotonic()

    def checkpoint(_record):
        nonlocal last
        if time.monotonic() - last < payload["checkpoint_s"]:
            return
        t0 = time.perf_counter()
        rec = cp.save(payload["ids"], phase="periodic", included_in_pipeline=True)
        elapsed = time.perf_counter() - t0
        print(f"Checkpoint verified: {rec['versions']} versions, {elapsed:.1f}s", flush=True)
        last = time.monotonic()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(local / "work/run.log", encoding="utf-8"),
        ],
    )
    run(
        payload["ids"],
        data_root=local / "data/corpus",
        work_dir=local / "work",
        references=payload["references"],
        snapshot=Path(payload["snapshot"]) if payload.get("snapshot") else None,
        progress=False,
        label=payload["owner"],
        on_version=checkpoint,
        adaptive_pacing=payload.get("adaptive_pacing", False),
        source_mode=payload.get("source_mode", "arxiv"),
        s3_index=json.loads(Path(payload["s3_index"]).read_text(encoding="utf-8"))
        if payload.get("s3_index")
        else None,
    )


def export_evidence(cfg: BenchmarkConfig, local: Path) -> Path:
    from src.analysis.stats import main as stats

    ids = [i for c in plan_chunks(cfg) for i in c.ids]
    stats(
        [
            "--ids",
            ",".join(ids),
            "--data-root",
            str(local / "data/corpus"),
            "--work-dir",
            str(local / "work"),
            "--out",
            str(local / "book_csv"),
        ]
    )
    path = local / "bench_results.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for folder in (local / "work", local / "book_csv"):
            for file in folder.rglob("*"):
                if file.is_file() and file.name != "run.lock":
                    archive.write(file, file.relative_to(local).as_posix())
    return path


def export_rescue(local: Path, stage: Path | None = None) -> Path:
    """Raw local recovery package: no Drive access, QA or stats regeneration."""
    path = local / "rescue_results.zip"
    folders = [(local / name, name) for name in ("work", "data", "book_csv")]
    if stage is not None:
        folders.append((stage, "telemetry_staging"))
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for folder, prefix in folders:
            for file in folder.rglob("*"):
                if file.is_file() and file.name != "run.lock":
                    archive.write(file, f"{prefix}/{file.relative_to(folder).as_posix()}")
    return path


def _cooldown(measurements, seconds: float) -> None:
    """Sleep in one-second steps so the session sampler keeps checking while we wait."""
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        measurements.check()
        time.sleep(min(1.0, left))


def timing_audit(local: Path) -> dict:
    """A hard kill can lose the last interval; never invent an exact final runtime."""
    profiles = list((local / "work/profile").glob("*"))
    unfinished = [
        p.name for p in profiles if p.is_dir() and not (p / "profile_summary.json").exists()
    ]
    from src.analysis.measurement_exports import paper_timing_report
    from src.benchmark.measurements import session_report

    sessions, _ = session_report(local)
    manifest_path = local / "work/manifest.json"
    required = (
        json.loads(manifest_path.read_text(encoding="utf-8")).get("required_ids", [])
        if manifest_path.exists()
        else []
    )
    _, paper_audit = paper_timing_report([local / "work"], required)
    paper_complete = paper_audit["complete"]
    result = dict(
        timing_complete=bool(profiles)
        and not unfinished
        and sessions["complete"]
        and paper_complete,
        unfinished_profiles=sorted(unfinished),
        measurement_complete=sessions["complete"],
        paper_timing_complete=paper_complete,
        paper_timing_errors=paper_audit["errors"],
        incomplete_sessions=sessions["incomplete_sessions"],
        observed_wall_lower_bound_s=sessions["observed_wall_lower_bound_s"],
    )
    write_json(local / "work/timing_audit.json", result)
    return result


def run_benchmark(
    cfg: BenchmarkConfig,
    *,
    drive_root: Path,
    local_root: Path,
    revision: str,
    team_id: str,
    resume: bool = False,
) -> dict:
    """Run in the notebook's foreground; all real crawl work lives in profiled children."""
    import psutil

    hub = None
    if cfg.storage_backend == "huggingface":
        from src.benchmark.huggingface import HubStore

        drive_root.mkdir(parents=True, exist_ok=True)
        hub = HubStore(cfg.hf_repo_id, drive_root / ".hf-cache")
        saved = hub.read(f"runs/{cfg.run_id}/MANIFEST.json", missing_ok=True)
        if saved is not None:
            write_json(drive_root / "runs" / cfg.run_id / "MANIFEST.json", json.loads(saved))
        prepare_drive(drive_root, team_id, initialize=True)
    else:
        prepare_drive(drive_root, team_id)
    local, remote = local_root / cfg.run_id, drive_root / "runs" / cfg.run_id
    checkpoint_published = False
    child = None
    measurements = None
    run_ready = False
    result = None
    incomplete: list[dict] = []
    session_start = time.perf_counter()
    try:
        manifest = prepare_run(cfg, drive_root / "runs", revision, resume=resume)
        if hub is not None and not resume:
            claim_hf_run(hub, cfg.run_id, manifest)
        from src.benchmark.measurements import SessionMeasurements

        session_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        if not resume and local.exists():
            raise FileExistsError("Local run directory exists; use a new run ID")
        measurements = SessionMeasurements(
            local_root / ".measurements" / cfg.run_id / session_id,
            remote,
            local,
            session_id,
            flush_s=120 if hub is not None else 30,
            publisher=(
                lambda files: hub.commit(
                    {
                        f"runs/{cfg.run_id}/{path.relative_to(remote).as_posix()}": json.dumps(
                            value
                        ).encode()
                        for path, value in files.items()
                    },
                    "M1 telemetry",
                )
            )
            if hub is not None
            else None,
            extra_disk_paths=([Path(cfg.snapshot)] if cfg.snapshot else [])
            + (
                [
                    remote,
                    drive_root / ".hf-cache",
                    Path(os.environ.get("HF_XET_CACHE", str(drive_root / ".hf-xet-cache"))),
                ]
                if hub is not None
                else []
            ),
        )
        measurements.start()
        cp = checkpoint_backend(local, remote, repo_id=cfg.hf_repo_id if hub else None, hub=hub)
        if resume:
            cp.restore()  # fresh local destination required; never delete existing data
        elif local.exists():
            raise FileExistsError("Local run directory exists; use a new run ID")
        work = local / "work"
        work.mkdir(parents=True, exist_ok=True)
        write_json(work / "manifest.json", manifest)
        run_ready = True
        write_json(
            work / f"sessions/{session_id}.json",
            dict(
                code_revision=revision,
                python=sys.version,
                platform=platform.platform(),
                cpu_count=psutil.cpu_count(),
                ram_bytes=psutil.virtual_memory().total,
                dependencies={d.metadata["Name"]: d.version for d in distributions()},
                started_at=datetime.now(UTC).isoformat(),
            ),
        )
        chunks = plan_chunks(cfg)
        all_ids = [i for c in chunks for i in c.ids]
        # Establish a recoverable run before scanning the snapshot or large bundles.
        cp.save([], phase="initial")
        snapshot_index = None
        if cfg.snapshot:
            from src.crawler.snapshot import prepare_snapshot_index

            measurements.phase = "snapshot-index"
            snapshot_index = work / "snapshot_index.jsonl"
            prepared = prepare_snapshot_index(
                cfg.snapshot,
                all_ids,
                snapshot_index,
                expected_sha256=manifest["snapshot_sha256"],
            )
            write_json(work / f"snapshot_preparation/{session_id}.json", prepared)
            print(f"Snapshot: {prepared['found']}/{len(all_ids)} IDs indexed", flush=True)
        s3_index_path = None
        phases = [("arxiv", chunk) for chunk in chunks]
        if cfg.source_mode != "arxiv":
            from src.crawler.s3_partition import partition_snapshot

            partition = partition_snapshot(snapshot_index, all_ids)
            if partition.missing:
                raise ValueError(f"Snapshot missing or invalid for {len(partition.missing)} IDs")
            s3_targets = partition.only_v1 if cfg.source_mode == "arxiv_s3" else all_ids
            measurements.phase = "s3-bundle-index"
            s3_index_path = work / "s3_index.json"
            s3_started = time.perf_counter()
            write_json(
                s3_index_path,
                prepare_s3_index(Path(cfg.s3_manifest), Path(cfg.s3_bundle_dir), s3_targets),
            )
            write_json(
                work / f"s3_index_sessions/{session_id}.json",
                {
                    "seconds": round(time.perf_counter() - s3_started, 3),
                    "target_ids": len(s3_targets),
                    "manifest_sha256": manifest["s3_manifest_sha256"],
                },
            )
            if cfg.source_mode == "arxiv_s3":
                ordered = order_hybrid_chunks(chunks, partition)
                singles = [chunk for name, chunk in ordered if name == "only_v1"]
                multis = [chunk for name, chunk in ordered if name == "multi_version"]
                phases = (
                    [("s3", chunk) for chunk in singles]
                    + [("fallback", chunk) for chunk in singles]
                    + [("multi_version", chunk) for chunk in multis]
                )
            else:
                phases = [("s3", chunk) for chunk in chunks]
        last_exit = None
        # A chunk that stays incomplete (arXiv 429 beyond the retry budget) is retried after
        # a cooldown, then recorded and skipped: one stubborn version must not stop the run.
        queue = deque((phase, chunk, 1) for phase, chunk in phases)
        while queue:
            phase, chunk, tries = queue.popleft()
            measurements.check()
            phase_references = cfg.references and not (
                phase == "s3" and cfg.source_mode == "arxiv_s3"
            )
            if _chunk_complete(chunk, local, phase_references):
                print(f"Verified complete: {chunk.owner} {chunk.offset}", flush=True)
                continue
            if last_exit is not None:
                time.sleep(max(0.0, 3.1 - (time.monotonic() - last_exit)))
            attempt = f"{chunk.owner}-{chunk.offset:04d}-{uuid.uuid4().hex}"
            prof = work / "profile" / attempt
            prof.mkdir(parents=True)
            payload = dict(
                ids=list(chunk.ids),
                owner=chunk.owner,
                local=str(local),
                remote=str(remote),
                checkpoint_s=cfg.checkpoint_s,
                references=phase_references,
                snapshot=str(snapshot_index) if snapshot_index else None,
                hf_repo_id=cfg.hf_repo_id if hub else None,
                adaptive_pacing=cfg.adaptive_pacing,
                source_mode="s3" if phase == "s3" else "arxiv",
                s3_index=str(s3_index_path) if phase == "s3" else None,
            )
            payload_path = work / "chunk.json"
            write_json(payload_path, payload)
            write_json(
                prof / "attempt.json",
                dict(
                    attempt=attempt,
                    owner=chunk.owner,
                    ids=list(chunk.ids),
                    phase=phase,
                    planned_at=datetime.now(UTC).isoformat(),
                    state="launch-intent",
                ),
            )
            # Durable intent BEFORE Popen: even a kill before first periodic save
            # must leave evidence of an attempt with potentially missing runtime.
            checkpoint_backend(
                local,
                remote,
                repo_id=cfg.hf_repo_id if hub else None,
                hub=hub,
            ).save(list(chunk.ids), phase="prelaunch")
            cmd = [
                sys.executable,
                "-m",
                "src.utils.profiler",
                "--out",
                str(prof),
                "--watch",
                str(local / "data"),
                "--watch",
                str(work),
                "--output",
                str(local / "data/corpus"),
                "--",
                sys.executable,
                "-m",
                "src.benchmark.runner",
                "--chunk",
                str(payload_path),
            ]
            if Path("/usr/bin/time").is_file():
                cmd = ["/usr/bin/time", "-v", "-o", str(prof / "time_v.log"), *cmd]
            print(
                f"=== {phase} {chunk.owner} offset={chunk.offset} IDs={len(chunk.ids)} ===",
                flush=True,
            )
            measurements.phase = "crawl-chunk"
            with (prof / "console.log").open("wb") as console:
                child = subprocess.Popen(
                    cmd,
                    start_new_session=sys.platform != "win32",
                    stdout=console,
                    stderr=subprocess.STDOUT,
                )
            console_offset = 0
            label = (
                f"{phase} {chunk.owner} papers" if cfg.snapshot_group != "all" else "Source papers"
            )
            paper_bar = tqdm(total=len(chunk.ids), desc=label, unit="paper", file=sys.stdout)
            version_bar = (
                tqdm(total=0, desc=f"{chunk.owner} versions", unit="version", file=sys.stdout)
                if cfg.snapshot_group == "multi_version"
                else None
            )

            def update_paper_bar(count, total, bar=paper_bar):
                bar.total = total
                bar.n = count
                bar.refresh()

            def update_version_bar(count, total, bar=version_bar):
                if bar is not None:
                    bar.total = total
                    bar.n = count
                    bar.refresh()

            try:
                while child.poll() is None:
                    measurements.check()
                    console_offset = forward_paper_progress(
                        prof / "console.log", console_offset, update_paper_bar, update_version_bar
                    )
                    time.sleep(1)
                forward_paper_progress(
                    prof / "console.log", console_offset, update_paper_bar, update_version_bar
                )
            except BaseException:
                # Stop the entire profiler/crawler process tree before checkpointing.
                try:
                    process = psutil.Process(child.pid)
                    processes = process.children(recursive=True) + [process]
                    for proc in processes:
                        try:
                            proc.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    _, alive = psutil.wait_procs(processes, timeout=10)
                    for proc in alive:
                        try:
                            proc.kill()
                        except psutil.NoSuchProcess:
                            pass
                except psutil.NoSuchProcess:
                    pass
                finally:
                    child.wait()
                    child = None
                raise
            finally:
                paper_bar.close()
                if version_bar is not None:
                    version_bar.close()
            last_exit = time.monotonic()
            code, child = child.returncode, None
            # Child may have published periodic checkpoints; refresh the parent index.
            cp = checkpoint_backend(
                local,
                remote,
                repo_id=cfg.hf_repo_id if hub else None,
                hub=hub,
            )
            sync_start = time.perf_counter()
            measurements.phase = "post-chunk-sync"
            checkpoint = cp.save(list(chunk.ids), phase="post-chunk")
            sync_s = time.perf_counter() - sync_start
            with (work / "attempts.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        dict(
                            attempt=attempt,
                            exit_code=code,
                            sync_s=sync_s,
                            checkpoint=checkpoint["generation"],
                        )
                    )
                    + "\n"
                )
            print(
                f"{cfg.storage_backend} checkpoint verified; post-chunk sync={sync_s:.1f}s",
                flush=True,
            )
            if code:
                raise RuntimeError(
                    f"Chunk exit {code}; inspect {prof / 'console.log'} and work/run.log"
                )
            if phase == "s3" and cfg.source_mode == "arxiv_s3":
                continue  # fallback phase handles missing/unverified sources
            if not _chunk_complete(chunk, local, phase_references):
                if phase == "s3":
                    incomplete.append(dict(owner=chunk.owner, offset=chunk.offset, tries=tries))
                    print("S3 source missing or unverified; recorded and continuing", flush=True)
                    continue
                if tries < cfg.chunk_attempts:
                    wait = cfg.chunk_cooldown_s * tries
                    print(
                        f"Chunk {chunk.owner} {chunk.offset} incomplete (try {tries}/"
                        f"{cfg.chunk_attempts}); cooling down {wait:.0f}s",
                        flush=True,
                    )
                    measurements.phase = "cooldown"
                    _cooldown(measurements, wait)
                    queue.appendleft((phase, chunk, tries + 1))
                else:
                    incomplete.append(dict(owner=chunk.owner, offset=chunk.offset, tries=tries))
                    print(
                        f"Chunk {chunk.owner} {chunk.offset} still incomplete after {tries} "
                        "tries; continuing, resume later to repair it",
                        flush=True,
                    )
                continue
        measurements.phase = "qa-and-reports"
        result = coverage(cfg, local)
        result["incomplete_chunks"] = incomplete
        result["final_corpus_complete"] = result["final_complete"]
        result.update(timing_audit(local))
        result["final_complete"] = result["final_complete"] and result["timing_complete"]
        write_json(work / "coverage.json", result)
        export_evidence(cfg, local)
        # HF's finally checkpoint persists these same reports.
        if hub is None:
            cp.save(all_ids, phase="final-reports")
        checkpoint_published = True
        return result
    finally:
        primary_error = sys.exception()
        cleanup_errors = []

        def cleanup(phase, action):
            try:
                return action()
            except Exception as exc:
                cleanup_errors.append(dict(phase=phase, error=f"{type(exc).__name__}: {exc}"))
                logging.exception("Cleanup failed during %s; preserving local evidence", phase)
                return None

        # A hard runtime loss cannot execute this block: only verified checkpoints survive.
        if run_ready and child is None:
            try:
                if measurements is not None:
                    measurements.phase = "final-sync"
                checkpoint_backend(
                    local,
                    remote,
                    repo_id=cfg.hf_repo_id if hub else None,
                    hub=hub,
                ).save([i for c in plan_chunks(cfg) for i in c.ids], phase="final")
                checkpoint_published = True
            except Exception as exc:
                cleanup_errors.append(
                    dict(phase="final-checkpoint", error=f"{type(exc).__name__}: {exc}")
                )
                logging.exception("Final checkpoint failed; preserve local data")
                checkpoint_published = False
        if measurements is not None:
            from src.benchmark.measurements import collect_measurements

            measurement_summary = cleanup(
                "local-measurement-finalization",
                lambda: measurements.finish(publish_remote=checkpoint_published),
            )
            if measurement_summary and not measurement_summary["complete"]:
                cleanup_errors.append(
                    dict(
                        phase="measurement-publication",
                        error=measurement_summary.get("telemetry_error", "Incomplete measurement"),
                    )
                )
            if checkpoint_published and measurement_summary and measurement_summary["complete"]:
                cleanup(
                    "remote-measurement-collection", lambda: collect_measurements(local, remote)
                )
        if run_ready:
            session = dict(
                seconds_through_final_sync=time.perf_counter() - session_start,
                checkpoint_published=checkpoint_published,
                ended_at=datetime.now(UTC).isoformat(),
            )
            cleanup(
                "local-session-summary",
                lambda: write_json(local / f"work/session_totals/{session_id}.json", session),
            )
            if checkpoint_published:
                cleanup(
                    "remote-session-summary",
                    lambda: write_json(remote / f"sessions/{session_id}.json", session),
                )
            if result is None:
                result = cleanup("local-QA", lambda: coverage(cfg, local)) or {}
                result["incomplete_chunks"] = incomplete
                result["final_corpus_complete"] = result.get("final_complete", False)
            result.update(
                cleanup("timing-audit", lambda: timing_audit(local)) or {"timing_complete": False}
            )
            result["final_complete"] = (
                result.get("final_corpus_complete", False)
                and result["timing_complete"]
                and not cleanup_errors
            )
            cleanup("local-coverage", lambda: write_json(local / "work/coverage.json", result))
            diagnostic = dict(
                primary_error=f"{type(primary_error).__name__}: {primary_error}"
                if primary_error
                else None,
                errors=cleanup_errors,
            )
            cleanup(
                "local-diagnostics",
                lambda: write_json(local / "work/cleanup_errors.json", diagnostic),
            )
            # Include the last checkpoint event and session total in the downloadable ZIP.
            evidence = cleanup("local-evidence-export", lambda: export_evidence(cfg, local))
            if (
                evidence is not None
                and hub is not None
                and checkpoint_published
                and not cleanup_errors
            ):
                cleanup(
                    "HF-final-evidence-publication",
                    lambda: checkpoint_backend(local, remote, repo_id=cfg.hf_repo_id, hub=hub).save(
                        [i for c in plan_chunks(cfg) for i in c.ids], phase="evidence-publication"
                    ),
                )
            if cleanup_errors:
                result["final_complete"] = False
                cleanup("local-coverage", lambda: write_json(local / "work/coverage.json", result))
            cleanup(
                "local-diagnostics",
                lambda: write_json(local / "work/cleanup_errors.json", diagnostic),
            )
            if evidence is None:
                rescue = cleanup(
                    "raw-rescue-export",
                    lambda: export_rescue(
                        local, measurements.stage if measurements is not None else None
                    ),
                )
                if rescue is not None:
                    print(f"Raw rescue evidence saved locally: {rescue}", flush=True)
        if cleanup_errors:
            message = (
                f"Cleanup errors recorded in {local / 'work/cleanup_errors.json'}; keep local data."
            )
            if primary_error is not None:
                primary_error.add_note(message)
            else:
                raise RuntimeError(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk", type=Path, required=True)
    args = parser.parse_args()
    run_child(json.loads(args.chunk.read_text(encoding="utf-8")))
