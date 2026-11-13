"""Bind a resumable M2 run to the exact contents of its corpus roots."""

import hashlib
import json
import os
from pathlib import Path


def verify_corpus_identity(roots: list[Path], work_dir: Path) -> str:
    digest = hashlib.sha256()
    for number, root in enumerate(map(Path, roots)):
        if not root.is_dir() or root.is_symlink():
            raise ValueError(f"Missing or unsafe corpus root: {root}")
        digest.update(f"root:{number}\n".encode())
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError(f"Corpus symlink: {rel}")
            if path.is_dir():
                digest.update(f"d:{rel}\n".encode())
            elif path.is_file():
                with path.open("rb") as stream:
                    file_hash = hashlib.file_digest(stream, "sha256").hexdigest()
                digest.update(f"f:{rel}\0{file_hash}\n".encode())
            else:
                raise ValueError(f"Unsupported corpus entry: {rel}")
    value = digest.hexdigest()
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    identity = work / "corpus-input-identity.json"
    expected = {"sha256": value, "root_count": len(roots)}
    if identity.exists():
        if json.loads(identity.read_text(encoding="utf8")) != expected:
            raise ValueError("corpus input changed; use a new run")
    elif (work / "shards.jsonl").exists():
        raise ValueError("Existing run has no corpus identity; use a new run")
    else:
        temp = identity.with_name(identity.name + ".part")
        temp.write_text(json.dumps(expected) + "\n", encoding="utf8")
        os.replace(temp, identity)
    return value


def verify_run_config(work_dir: Path, config: dict) -> None:
    """Refuse to resume an enriched run with different parser settings."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    identity = work / "parser-config-identity.json"
    if identity.exists():
        if json.loads(identity.read_text(encoding="utf8")) != config:
            raise ValueError("parser configuration changed; use a new run")
    elif (work / "shards.jsonl").exists():
        raise ValueError("Existing run has no parser configuration identity; use a new run")
    else:
        temp = identity.with_name(identity.name + ".part")
        temp.write_text(json.dumps(config, sort_keys=True) + "\n", encoding="utf8")
        os.replace(temp, identity)


def verify_restored_checkpoint(local: Path, index: dict) -> None:
    """Validate a cached restore against its pinned remote checkpoint and file hashes."""
    from src.benchmark.checkpoints import Checkpoints

    local = Path(local)
    head = json.loads((local / ".checkpoint-head.json").read_text(encoding="utf8"))
    for key in ("generation", "files", "directories"):
        if head.get(key) != index.get(key):
            raise ValueError(f"Cached checkpoint differs from pinned index: {key}")
    for name, expected in index["files"].items():
        if not Checkpoints.safe_name(name):
            raise ValueError(f"Unsafe checkpoint path: {name}")
        # restore() reconstructs telemetry outside the committed parser inputs.
        if not (name.startswith("data/corpus/") or name == "work/versions.jsonl"):
            continue
        path = local / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Cached checkpoint file missing or unsafe: {name}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected:
            raise ValueError(f"Cached checkpoint file changed: {name}")
    for name in index["directories"]:
        if not Checkpoints.safe_name(name) or not (local / name).is_dir():
            raise ValueError(f"Cached checkpoint directory missing or unsafe: {name}")

    corpus = local / "data" / "corpus"
    if corpus.exists():
        expected_files = {name for name in index["files"] if name.startswith("data/corpus/")}
        for path in corpus.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Cached checkpoint contains symlink: {path}")
            if path.is_file() and path.relative_to(local).as_posix() not in expected_files:
                raise ValueError(f"Cached checkpoint has extra corpus file: {path}")

    if "work/versions.jsonl" not in index["files"]:
        raise ValueError("Cached checkpoint index lacks work/versions.jsonl")
