"""Inspect verified arXiv bulk bundles without assuming a member's version."""

from __future__ import annotations

import hashlib
import re
import shutil
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from src.crawler.extract import extract_stream
from src.crawler.s3_prepare import Bundle, _verify


def index_verified_bundle(path: Path, bundle: Bundle, ids: set[str]) -> dict[str, dict]:
    """Index target members after verifying the outer tar; version remains unverified."""
    if not _verify(path, bundle):
        raise ValueError(f"Bundle checksum mismatch: {bundle.key}")
    found: dict[str, dict] = {}
    with tarfile.open(path, "r:") as archive:
        for item in archive:
            member = PurePosixPath(item.name)
            if not item.isfile() or member.is_absolute() or ".." in member.parts:
                continue
            match = re.fullmatch(r"(\d{4}\.\d{4,5})(?:v\d+)?(?:\.[a-zA-Z0-9]+)*", member.name)
            if not match or match[1] not in ids:
                continue
            pid = match[1]
            if pid in found:
                raise ValueError(f"Ambiguous duplicate member for {pid} in {bundle.key}")
            found[pid] = {
                "status": "version_unverified",
                "bundle": bundle.key,
                "bundle_md5": bundle.md5,
                "member": item.name,
                "offset": item.offset_data,
                "size": item.size,
                "file_size": path.stat().st_size,
                "file_mtime_ns": path.stat().st_mtime_ns,
            }
    return found


def index_bundle_set(directory: Path, bundles: list[Bundle], ids: set[str]) -> dict[str, dict]:
    """Verify selected bundles and report an explicit status for every requested ID."""
    result: dict[str, dict] = {}
    for bundle in bundles:
        path = directory / PurePosixPath(bundle.key).name
        found = index_verified_bundle(path, bundle, ids)
        duplicates = set(found) & set(result)
        if duplicates:
            raise ValueError(f"Ambiguous IDs across bundles: {sorted(duplicates)}")
        result.update(found)
    for pid in ids - result.keys():
        result[pid] = {"status": "source_missing"}
    return result


def infer_v1(snapshot_dates: list[str], bundle_timestamp: str) -> bool:
    """Heuristic only: one snapshot version and a bundle at least one day newer."""
    if len(snapshot_dates) != 1:
        return False
    try:
        submitted = datetime.fromisoformat(snapshot_dates[0].replace("Z", "+00:00"))
        if submitted.tzinfo is None:
            return False
        bundle_time = datetime.strptime(bundle_timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return submitted <= bundle_time - timedelta(days=1)
    except (ValueError, TypeError):
        return False


def extract_inferred_v1(
    path: Path, entry: dict, destination: Path, dates: list[str], timestamp: str
):
    """Extract an inferred v1; the caller records the snapshot and bundle identities."""
    if not infer_v1(dates, timestamp):
        raise ValueError("Cannot infer v1 from snapshot and bundle timestamp")
    stat = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (entry["file_size"], entry["file_mtime_ns"]):
        raise ValueError("Bundle changed after checksum verification")

    class LimitedReader:
        def __init__(self, stream, remaining):
            self.stream, self.remaining = stream, remaining

        def read(self, size=-1):
            if size is None or size < 0:
                size = self.remaining
            data = self.stream.read(min(size, self.remaining))
            self.remaining -= len(data)
            return data

    with path.open("rb") as stream:
        stream.seek(entry["offset"])
        source = LimitedReader(stream, entry["size"])
        res = extract_stream(
            source, destination, filename_hint=entry["member"], size_hint=entry["size"]
        )
    if res.kind in {"empty", "html"}:
        raise ValueError(f"Suspicious S3 source kind: {res.kind}")
    tex_files = [name for name in res.files if name.lower().endswith(".tex")]
    if tex_files and all((destination / name).stat().st_size == 0 for name in tex_files):
        shutil.rmtree(destination)
        destination.mkdir()
        res.files = []
        res.bytes_after = 0
        res.has_tex = False
    return {
        "status": "ok" if res.has_tex else "no_tex",
        "kind": res.kind,
        "files": res.files,
        "archive_bytes": res.archive_bytes,
        "bytes_before": res.bytes_before,
        "bytes_after": res.bytes_after,
        "skipped_unsafe": res.skipped_unsafe,
        "dropped": res.dropped,
        "source": "s3",
        "bundle": entry["bundle"],
        "bundle_md5": entry["bundle_md5"],
        "bundle_timestamp": timestamp,
        "member": entry["member"],
        "version_evidence": "inferred_snapshot_bundle_timestamp",
    }


def extract_verified_member(path: Path, entry: dict, destination: Path, expected_sha256: str):
    """Accept source only with a trusted digest for this exact paper and version."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("A valid version SHA-256 is required")
    with tarfile.open(path, "r:") as archive:
        member = archive.getmember(entry["member"])
        if (
            not member.isfile()
            or member.size != entry["size"]
            or member.offset_data != entry["offset"]
        ):
            raise ValueError("Bundle member changed after indexing")
        digest = hashlib.sha256()
        with archive.extractfile(member) as source:
            while block := source.read(8 * 1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("Source does not match the trusted version SHA-256")
        with archive.extractfile(member) as source:
            return extract_stream(
                source, destination, filename_hint=member.name, size_hint=member.size
            )
