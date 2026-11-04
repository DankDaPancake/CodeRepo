"""Verified archives of completed papers; original corpus paths are preserved."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import time
from pathlib import Path

from src.benchmark.checkpoints import Checkpoints, digest
from src.qa.validate import validate_range
from src.utils.ids import to_folder_name


def verify_batch(path: Path, *, expected_sha256: str | None = None) -> dict:
    """Read the complete archive and verify member hashes, names and directories."""
    if expected_sha256 is not None and digest(path) != expected_sha256:
        raise ValueError("Batch archive checksum mismatch")
    with tarfile.open(path, "r:gz") as archive:
        manifest_file = archive.extractfile("BATCH.json")
        if manifest_file is None:
            raise ValueError("Batch manifest missing")
        manifest = json.load(manifest_file)
        expected = set(manifest["files"]) | set(manifest["directories"]) | {"BATCH.json"}
        seen = set()
        for member in archive:
            name = member.name.rstrip("/")
            if not Checkpoints.safe_name(name) or name not in expected or name in seen:
                raise ValueError(f"Unsafe/unexpected/duplicate batch member: {name}")
            seen.add(name)
            if name in manifest["directories"]:
                if not member.isdir():
                    raise ValueError(f"Expected directory: {name}")
            elif not member.isfile():
                raise ValueError(f"Expected regular file: {name}")
            elif name != "BATCH.json":
                with archive.extractfile(member) as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != manifest["files"][name]:
                    raise ValueError(f"Batch member checksum mismatch: {name}")
        if seen != expected:
            raise ValueError("Batch members missing")
    return manifest


def pack_batch(local: Path, ids: list[str], records: list[dict], target: Path,
               *, provenance: dict, compresslevel: int = 1) -> dict:
    """Publish only fully verified archives; failed packs leave no new target."""
    started = time.perf_counter()
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Batch IDs must be nonempty and unique")
    if target.exists():
        raise FileExistsError(target)
    data = local / "data/corpus"
    state = {(row["arxiv_id"], row["version"]): row for row in records}
    issues, _ = validate_range(ids, data, owner="batch", versions_log=state,
                               require_references=True)
    if any(issue.severity == "error" for issue in issues):
        raise ValueError("Batch source/reference QA failed")
    paths, directories, versions = {}, [], []
    for pid in ids:
        folder = data / to_folder_name(pid)
        refs = json.loads((folder / "references.json").read_text(encoding="utf-8"))
        if refs.get("status") not in ("ok", "not_found"):
            raise ValueError(f"Batch references incomplete: {pid}")
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        versions.extend(state[(pid, number)] for number in range(1, metadata["num_versions"] + 1))
        for path in [folder, *sorted(folder.rglob("*"))]:
            name = path.relative_to(local).as_posix()
            if path.is_symlink() or not Checkpoints.safe_name(name):
                raise ValueError(f"Unsafe batch path: {name}")
            if path.is_dir():
                directories.append(name)
            else:
                paths[name] = digest(path)
    manifest = dict(schema=1, ids=ids, versions=versions, files=paths,
                    directories=directories, provenance=provenance,
                    compression=dict(format="tar.gz", level=compresslevel))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="batch-", dir=target.parent) as temporary:
        packed = Path(temporary) / "batch.tar.gz"
        with tarfile.open(packed, "w:gz", compresslevel=compresslevel) as archive:
            content = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
            info = tarfile.TarInfo("BATCH.json")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
            for name in directories:
                archive.add(local / name, arcname=name, recursive=False)
            for name in paths:
                archive.add(local / name, arcname=name, recursive=False)
        verify_batch(packed)
        checksum = digest(packed)
        size = packed.stat().st_size
        packed.replace(target)
    return dict(path=str(target), sha256=checksum, bytes=size, papers=len(ids),
                versions=len(versions), seconds=time.perf_counter() - started)
