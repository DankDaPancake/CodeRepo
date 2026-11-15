"""Read M2 checkpoint assignments without modifying the original journal."""

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from src.utils.ids import to_folder_name


def inspect_run(
    root: Path, run_id: str, qa_revision: str, expected_shards: int | None = None
) -> tuple[dict, dict]:
    """Bind a QA session to the completed parse, journal and shard hash manifest."""
    root = Path(root)
    files = {
        "manifest": root / "M2_MANIFEST.json",
        "session": root / "SESSION_STATE.json",
        "summary": root / "work" / "run_summary.json",
        "journal": root / "work" / "shards.jsonl",
        "hashes": root / "work" / "shard-hashes.json",
    }
    raw = {name: path.read_bytes() for name, path in files.items()}
    manifest = json.loads(raw["manifest"])
    state = json.loads(raw["session"])
    summary = json.loads(raw["summary"])
    if manifest["m2_run_id"] != run_id or not qa_revision:
        raise ValueError("Run identity mismatch")
    sessions = state.get("sessions", [])
    if (
        not sessions
        or sessions[-1].get("status") != "complete"
        or sessions[-1].get("returncode") != 0
    ):
        raise ValueError("Parse session incomplete")
    assignments = read_assignments(files["journal"])
    if files["journal"].read_bytes() != raw["journal"]:
        raise ValueError("Journal changed during inspection")
    if summary.get("interrupted") is not False or summary.get("papers_committed_total") != len(
        assignments
    ):
        raise ValueError("Parse output incomplete")
    if manifest.get("run_mode") == "full" and len(assignments) != manifest.get("expected_ids"):
        raise ValueError("Full run incomplete")
    if manifest.get("run_mode") == "full":
        from src.parser.run import assigned_folders

        expected_folders = assigned_folders()
        actual_folders = {to_folder_name(paper) for paper in assignments}
        if len(expected_folders) != manifest["expected_ids"] or actual_folders != expected_folders:
            raise ValueError("Full run assigned IDs differ from the configured assignment")
    hashes = json.loads(raw["hashes"])
    expected = {f"shard-{number:05d}" for number in assignments.values()}
    present = {p.name for p in (root / "out").glob("shard-*")}
    if expected != set(hashes) or expected != present:
        raise ValueError("Committed shards differ from output or hash manifest")
    if expected_shards is not None and len(expected) != expected_shards:
        raise ValueError(f"Unexpected shard count: {len(expected)} != {expected_shards}")
    identity = {
        "run_id": run_id,
        "parser_revision": manifest["code_revision"],
        "qa_revision": qa_revision,
        "expected_shards": expected_shards,
        **{f"{name}_sha256": hashlib.sha256(data).hexdigest() for name, data in raw.items()},
    }
    return identity, hashes


def prepare_qa(
    root: Path, run_id: str, qa_id: str, qa_revision: str, expected_shards: int | None = None
) -> tuple[dict, dict]:
    """Create or verify a QA-only identity without altering the completed parse."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", qa_id):
        raise ValueError("Invalid QA run ID")
    root = Path(root)
    identity, hashes = inspect_run(root, run_id, qa_revision, expected_shards)
    identity["qa_id"] = qa_id
    parent = root / "qa"
    dest = parent / qa_id
    if parent.is_symlink() or dest.is_symlink():
        raise ValueError("Unsafe QA path")
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "identity.json"
    if path.exists():
        if path.is_symlink() or json.loads(path.read_text(encoding="utf8")) != identity:
            raise ValueError("QA identity changed; use a new QA ID")
    else:
        if any(dest.iterdir()):
            raise ValueError("QA identity missing from non-empty directory")
        temp = dest / ".identity.part"
        temp.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf8")
        os.replace(temp, path)
    return identity, hashes


def read_assignments(journal: Path) -> dict[str, int]:
    data = Path(journal).read_bytes()
    if not data or not data.endswith(b"\n"):
        raise ValueError("Journal is empty or incomplete")
    papers: dict[str, int] = {}
    folders: dict[str, str] = {}
    shards: set[int] = set()
    for line in data.splitlines():
        row = json.loads(line)
        number = row["shard"]
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ValueError("Invalid shard number")
        if number in shards:
            raise ValueError(f"Duplicate shard: {number}")
        shards.add(number)
        for record in row["papers"]:
            paper = record["arxiv_id"]
            if paper in papers:
                raise ValueError(f"Duplicate paper: {paper}")
            folder = to_folder_name(paper)
            if folder in folders:
                raise ValueError(f"Paper folder collision: {paper}")
            folders[folder] = paper
            papers[paper] = number
    return papers


def verify_shard(shard: Path, expected: dict[str, str]) -> None:
    shard = Path(shard)
    if shard.is_symlink() or not shard.is_dir():
        raise ValueError(f"Missing or unsafe shard: {shard}")
    files = {}
    for path in shard.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Unsafe shard symlink: {path}")
        if path.is_file():
            files[path.relative_to(shard).as_posix()] = path
    if set(files) != set(expected):
        raise ValueError(f"Shard files differ from manifest: {shard}")
    for name, path in files.items():
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected[name]:
            raise ValueError(f"Shard hash mismatch: {path}")


def verify_checkpoint(out: Path, journal: Path, hashes: dict, on_progress=None) -> dict[str, int]:
    assignments = read_assignments(journal)
    expected = {f"shard-{number:05d}" for number in assignments.values()}
    actual = {path.name for path in Path(out).glob("shard-*")}
    if expected != actual or expected != set(hashes):
        raise ValueError("Checkpoint shards differ from journal or hash manifest")
    for done, name in enumerate(sorted(expected), 1):
        verify_shard(Path(out) / name, hashes[name])
        if on_progress:
            on_progress(done, len(expected))
    return assignments


def restore_shards(remote: Path, local: Path, hashes: dict, on_progress=None) -> dict:
    """Copy verified shards atomically; existing local shards are never overwritten."""
    remote, local = Path(remote).resolve(), Path(local).resolve()
    if remote == local or remote.is_relative_to(local) or local.is_relative_to(remote):
        raise ValueError("Source and destination overlap")
    if any(not re.fullmatch(r"shard-\d{5,}", name) for name in hashes):
        raise ValueError("Invalid shard name")
    local.mkdir(parents=True, exist_ok=True)
    unexpected = {p.name for p in local.glob("shard-*")} - set(hashes)
    if unexpected:
        raise ValueError(f"Unexpected local shards: {sorted(unexpected)}")
    counts = {"copied": 0, "reused": 0}
    for done, name in enumerate(sorted(hashes), 1):
        dest = local / name
        if dest.exists() or dest.is_symlink():
            verify_shard(dest, hashes[name])
            counts["reused"] += 1
        else:
            source = remote / name
            if source.is_symlink() or not source.is_dir():
                raise ValueError(f"Missing or unsafe source: {source}")
            required = 0
            for relative in hashes[name]:
                part = PurePosixPath(relative)
                if (
                    not relative
                    or part.is_absolute()
                    or ".." in part.parts
                    or "\\" in relative
                    or ":" in relative
                ):
                    raise ValueError(f"Unsafe shard file path: {relative}")
                file = source / relative
                if file.is_symlink() or not file.is_file():
                    raise ValueError(f"Missing or unsafe source file: {file}")
                required += file.stat().st_size
            if shutil.disk_usage(local).free < required:
                raise OSError(f"Insufficient free space for {name}: need {required} bytes")
            with tempfile.TemporaryDirectory(prefix=".qa-shard-", dir=local) as tmp:
                staging = Path(tmp) / name
                shutil.copytree(source, staging, symlinks=True)
                verify_shard(staging, hashes[name])
                staging.rename(dest)
            counts["copied"] += 1
        if on_progress:
            on_progress(done, len(hashes))
    return counts
