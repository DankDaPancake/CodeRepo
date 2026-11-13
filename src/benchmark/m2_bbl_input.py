"""Validate and index independently recovered bibliography files for M2."""

import hashlib
from pathlib import Path, PurePosixPath

from src.benchmark.recovery_review import read_journal
from src.utils.ids import to_folder_name


def load_bbl_index(recovery_dir: Path) -> dict[tuple[str, int], list[Path]]:
    root = Path(recovery_dir).resolve()
    records = read_journal(root / "versions.jsonl")
    result = {}
    used = set()
    for key, record in records.items():
        if record["status"] != "recovered":
            continue
        entries = record.get("files")
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"Recovered record has no files: {key}")
        paths = []
        prefix = ("files", to_folder_name(key[0]), f"v{key[1]}")
        for item in entries:
            name = item["path"]
            if not isinstance(name, str):
                raise ValueError(f"Unsafe BBL path: {name}")
            rel = PurePosixPath(name)
            if (
                "\\" in name
                or rel.is_absolute()
                or ".." in rel.parts
                or rel.parts[:3] != prefix
                or not name.lower().endswith(".bbl")
            ):
                raise ValueError(f"Unsafe BBL path: {name}")
            path = root.joinpath(*rel.parts)
            if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
                raise ValueError(f"Symlink in BBL path: {name}")
            if path in used:
                raise ValueError(f"Duplicate BBL path: {name}")
            used.add(path)
            if not path.is_file() or path.stat().st_size != item["bytes"]:
                raise ValueError(f"BBL integrity failure: {name}")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != item["sha256"]:
                raise ValueError(f"BBL integrity failure: {name}")
            paths.append(path)
        result[key] = sorted(paths)
    return result


def verify_run_identity(recovery_dir: Path, work_dir: Path) -> dict[tuple[str, int], list[Path]]:
    """Verify all BBL content and bind the journal identity to a work directory."""
    import json

    root = Path(recovery_dir)
    index = load_bbl_index(root)
    journal_hash = hashlib.sha256((root / "versions.jsonl").read_bytes()).hexdigest()
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    identity = work / "bbl-input-identity.json"
    expected = {"journal_sha256": journal_hash}
    if identity.exists():
        if json.loads(identity.read_text(encoding="utf8")) != expected:
            raise ValueError("BBL input changed; use a new run")
    elif (work / "shards.jsonl").exists():
        raise ValueError("Existing run has no BBL input identity; use a new run")
    else:
        identity.write_text(json.dumps(expected) + "\n", encoding="utf8")
    return index


def load_bbl_hashes(recovery_dir: Path, index: dict) -> dict[Path, str]:
    """Load expected hashes for the indexed paths, rejecting an inconsistent journal."""
    root = Path(recovery_dir).resolve()
    records = read_journal(root / "versions.jsonl")
    hashes = {}
    for key, paths in index.items():
        record = records.get(key)
        if not record or record.get("status") != "recovered":
            raise ValueError(f"BBL journal changed: {key}")
        declared = {root / f["path"]: f["sha256"] for f in record["files"]}
        if set(declared) != set(paths):
            raise ValueError(f"BBL journal changed: {key}")
        hashes.update(declared)
    if set(index) != {k for k, v in records.items() if v.get("status") == "recovered"}:
        raise ValueError("BBL journal changed")
    return hashes


def validate_recovery_complete(recovery_dir: Path) -> dict:
    """Require the completed recovery journal to account for every candidate."""
    import json
    from collections import Counter

    root = Path(recovery_dir)
    candidates = json.loads((root / "candidates.json").read_text(encoding="utf8"))
    keys = [(item["arxiv_id"], item["version"]) for item in candidates]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate recovery candidate")
    records = read_journal(root / "versions.jsonl")
    if set(keys) != set(records):
        raise ValueError("Recovery journal does not match candidates")
    counts = Counter(record["status"] for record in records.values())
    if set(counts) - {"recovered", "no_bbl", "unavailable"}:
        raise ValueError(f"Unresolved or invalid recovery status: {dict(counts)}")
    summary = json.loads((root / "summary.json").read_text(encoding="utf8"))
    papers = len({key[0] for key in keys})
    if (
        summary.get("versions") != dict(counts)
        or summary.get("candidate_versions") != len(keys)
        or summary.get("processed_versions") != len(records)
        or summary.get("candidate_papers") != papers
        or summary.get("papers") != papers
    ):
        raise ValueError("Recovery summary does not match candidates and journal")
    return dict(counts)
