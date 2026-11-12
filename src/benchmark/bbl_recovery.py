"""Recover dropped BBL files into an independent, resumable corpus."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from src.benchmark.recovery_review import _append, _inputs, _write, make_client, read_journal
from src.crawler.downloader import source_url
from src.crawler.http_client import BlockedError
from src.utils.ids import NEW_ID_RE, OLD_ID_RE, split_version, to_folder_name

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_BBL = 8 * 1024 * 1024
MAX_BBL_TOTAL = 64 * 1024 * 1024
MAX_UNPACKED = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 100_000


def select_candidates(journals):
    candidates = {}
    for run, path in sorted(journals.items()):
        for (pid, version), rec in read_journal(path).items():
            files = rec.get("files", [])
            if rec.get("status") != "ok" or any(
                f.lower().endswith((".bib", ".bbl")) for f in files
            ):
                continue
            if rec.get("dropped", {}).get(".bbl", {}).get("files", 0) < 1:
                continue
            if not (NEW_ID_RE.fullmatch(pid) or OLD_ID_RE.fullmatch(pid)) or split_version(pid)[1]:
                raise ValueError(f"Invalid arXiv ID: {pid}")
            item = candidates.setdefault(
                (pid, version), {"arxiv_id": pid, "version": version, "runs": [], "original": {}}
            )
            item["runs"].append(run)
            item["original"][run] = {
                "source": rec.get("source", "arxiv_http"),
                "version_evidence": rec.get("version_evidence"),
                "bundle": rec.get("bundle"),
                "dropped_bbl": rec["dropped"][".bbl"],
            }
    return [candidates[k] for k in sorted(candidates)]


def _safe_name(name):
    if "\\" in name or "\x00" in name or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"Unsafe archive member: {name}")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError(f"Unsafe archive member: {name}")
    return p.as_posix()


def inspect_archive(stream):
    """Read BBL members without extracting archive paths; reject unsafe/large files."""
    files, bib, seen = {}, [], set()
    total = 0

    def add(name, size, reader):
        nonlocal total
        total += size
        if total > MAX_UNPACKED:
            raise ValueError("Archive uncompressed size limit exceeded")
        if len(seen) >= MAX_MEMBERS:
            raise ValueError("Archive member count limit exceeded")
        name = _safe_name(name)
        if name in seen:
            raise ValueError(f"Duplicate member: {name}")
        seen.add(name)
        if name.lower().endswith(".bib"):
            bib.append(name)
        if name.lower().endswith(".bbl"):
            if size > MAX_BBL or sum(map(len, files.values())) + size > MAX_BBL_TOTAL:
                raise ValueError("BBL size limit exceeded")
            data = reader()
            if len(data) != size:
                raise ValueError("Truncated BBL member")
            files[name] = data

    stream.seek(0)
    if zipfile.is_zipfile(stream):
        stream.seek(0)
        with zipfile.ZipFile(stream) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Archive contains symlink")
                add(info.filename, info.file_size, lambda i=info: z.read(i))
    else:
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:*") as tar:
            for member in tar:
                if member.issym() or member.islnk():
                    raise ValueError("Archive contains link")
                if member.isfile():
                    add(member.name, member.size, lambda m=member: tar.extractfile(m).read())
    return files, sorted(bib)


def _consume(body, headers):
    with tempfile.TemporaryFile() as stream:
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = body.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARCHIVE:
                raise ValueError("Archive size limit exceeded")
            digest.update(chunk)
            stream.write(chunk)
        stream.seek(0)
        files, bib = inspect_archive(stream)
        return files, bib, digest.hexdigest(), size


def _valid_record(rec, root):
    if rec.get("status") != "recovered" or not rec.get("files"):
        return False
    for f in rec["files"]:
        path = root / f["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
            return False
    return True


def recover(journals, output, *, client=None, limit=None):
    states, output = _inputs(journals, output, "bbl-recovery")
    del states
    candidates = select_candidates(journals)
    _write(output / "candidates.json", candidates)
    lock = output / ".running"
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError(f"Output is locked: {lock}") from None
    try:
        (lock / "owner.json").write_text(
            json.dumps({"pid": os.getpid(), "started": datetime.now(UTC).isoformat()}),
            encoding="utf8",
        )
        path = output / "versions.jsonl"
        state = read_journal(path) if path.exists() else {}
        client = client or make_client()
        for item in candidates[:limit] if limit is not None else candidates:
            pid, version = item["arxiv_id"], item["version"]
            old = state.get((pid, version))
            if old and (
                _valid_record(old, output) or old.get("status") in {"no_bbl", "unavailable"}
            ):
                continue
            version_dir = output / "files" / to_folder_name(pid) / f"v{version}"
            if version_dir.is_symlink():
                raise ValueError(f"Version directory is a symlink: {version_dir}")
            if version_dir.exists():
                shutil.rmtree(version_dir)
            record = {
                **item,
                "checked_at": datetime.now(UTC).isoformat(),
                "url": source_url(pid, version),
            }
            try:
                response = client.stream(
                    record["url"], _consume, headers={"Accept-Encoding": "identity"}
                )
                record.update(http_status=response.status, attempts=response.attempts)
                if response.status in (404, 410):
                    record["status"] = "unavailable"
                elif response.status != 200:
                    record["status"] = "inconclusive"
                else:
                    files, bib, digest, size = response.value
                    record.update(
                        archive_sha256=digest, archive_bytes=size, bib_members=bib, files=[]
                    )
                    for name, data in files.items():
                        relative = Path("files") / to_folder_name(pid) / f"v{version}" / Path(name)
                        destination = output / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        temp = destination.with_name(destination.name + ".part")
                        temp.write_bytes(data)
                        os.replace(temp, destination)
                        sha = hashlib.sha256(data).hexdigest()
                        if hashlib.sha256(destination.read_bytes()).hexdigest() != sha:
                            raise OSError("Saved hash mismatch")
                        record["files"].append(
                            {
                                "path": relative.as_posix(),
                                "member": name,
                                "bytes": len(data),
                                "sha256": sha,
                            }
                        )
                    record["status"] = "recovered" if files else "no_bbl"
            except BlockedError as exc:
                record.update(status="inconclusive", reason=str(exc))
                _append(path, record)
                raise
            except ValueError as exc:
                record.update(status="unsafe_or_limit", reason=str(exc))
            except Exception as exc:
                record.update(status="inconclusive", reason=f"{type(exc).__name__}: {exc}")
            _append(path, record)
            state[(pid, version)] = record
            print(f"{pid}v{version}: {record['status']}", flush=True)
        summary = dict(Counter(r["status"] for r in state.values()))
        _write(
            output / "summary.json",
            {
                "versions": summary,
                "papers": len({k[0] for k in state}),
                "processed_versions": len(state),
                "candidate_versions": len(candidates),
                "candidate_papers": len({r["arxiv_id"] for r in candidates}),
            },
        )
        return summary
    finally:
        shutil.rmtree(lock)
