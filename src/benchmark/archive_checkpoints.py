"""Drive checkpoints with fixed ID batches, immutable tar.gz objects and no raw mirror.

Partial batches protect completed versions between phases. Only batches passing
source/reference QA are marked complete. Old objects are retained for recovery.
"""

from __future__ import annotations

import io
import json
import shutil
import tarfile
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from src.benchmark.batch_archives import verify_batch
from src.benchmark.checkpoints import Checkpoints, digest, write_json
from src.benchmark.measurements import collect_measurements, rows_digest
from src.qa.validate import validate_range
from src.run_pipeline import FINAL_STATUSES, load_version_state
from src.utils.ids import to_folder_name


class ArchiveCheckpoints(Checkpoints):
    """Same save/restore entrypoints as raw checkpoints; dedicated index schema."""

    def save(self, ids, *, phase="checkpoint", included_in_pipeline=False):
        result = super().save(ids, phase=phase, included_in_pipeline=included_in_pipeline)
        event = {key: result[key] for key in
                 ("generation", "packing_verify_s", "upload_verify_s", "bytes")}
        event.update(phase=phase, included_in_pipeline=included_in_pipeline)
        with (self.local / "work/archive_events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
        write_json(self.remote / "archive-events" / f"{result['generation']}.json", event)
        return result

    def _publish_archive(self, packed: Path, name: str) -> dict:
        checksum = digest(packed)
        relative = f"archives/{name}-{checksum}.tar.gz"
        destination = self.remote / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if digest(destination) != checksum:
                raise ValueError("Existing archive checksum mismatch")
        else:
            temporary = destination.with_suffix(f".tmp-{uuid.uuid4().hex}")
            try:
                shutil.copyfile(packed, temporary)
                if digest(temporary) != checksum:
                    raise ValueError("Uploaded archive checksum mismatch")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        return dict(path=relative, sha256=checksum, bytes=packed.stat().st_size)

    def _pack(self, paths, directories, manifest, staging, name):
        """Freeze mutable files so hashes and compressed content describe the same bytes."""
        started = time.perf_counter()
        frozen = staging / name
        frozen.mkdir()
        sources = {}
        for number, (relative, source) in enumerate(paths.items()):
            if not self.safe_name(relative) or source.is_symlink():
                raise ValueError(f"Unsafe archive file: {relative}")
            copy = frozen / str(number)
            shutil.copyfile(source, copy)
            sources[relative] = copy
        manifest = dict(manifest, files={name: digest(path) for name, path in sources.items()},
                        directories=sorted(directories))
        packed = staging / f"{name}.tar.gz"
        with tarfile.open(packed, "w:gz", compresslevel=1) as archive:
            content = json.dumps(manifest, sort_keys=True).encode("utf-8")
            member = tarfile.TarInfo("BATCH.json")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
            for relative in directories:
                if not self.safe_name(relative):
                    raise ValueError("Unsafe archive directory")
                member = tarfile.TarInfo(relative)
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            for relative, source in sources.items():
                archive.add(source, arcname=relative, recursive=False)
        verify_batch(packed)
        packing_s = time.perf_counter() - started
        started = time.perf_counter()
        result = self._publish_archive(packed, name)
        result.update(packing_verify_s=packing_s, upload_verify_s=time.perf_counter() - started)
        shutil.rmtree(frozen)
        packed.unlink()
        return result

    def _save(self, ids):
        head = self.local / ".archive-head.json"
        old = json.loads(head.read_text(encoding="utf-8")) if head.exists() else {}
        if (self.remote / "INDEX.json").exists() and not old:
            raise ValueError("Restore a verified archive checkpoint before saving")
        if old and old.get("schema") != "batch-archive-v1":
            raise ValueError("Wrong archive checkpoint schema")
        work = self.local / "work"
        manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
        required = manifest["required_ids"]
        size = manifest["config"]["archive_batch_size"]
        journal = work / "versions.jsonl"
        state = load_version_state(journal) if journal.exists() else {}
        by_paper = defaultdict(list)
        for (pid, _), row in sorted(state.items()):
            by_paper[pid].append(row)
        unknown = {pid for pid, _ in state} - set(required)
        if unknown:
            raise ValueError("Version journal contains IDs outside the run")
        provenance = {key: manifest.get(key) for key in ("code_revision", "snapshot_sha256")}
        provenance["run_id"] = manifest["config"]["run_id"]
        batches, copied, packing, uploading = [], 0, 0.0, 0.0
        staging_root = work / "tmp"
        staging_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="archive-", dir=staging_root) as temporary:
            staging = Path(temporary)
            for number, start in enumerate(range(0, len(required), size)):
                group = required[start:start + size]
                records, paths, directories = [], {}, set()
                for pid in group:
                    folder = f"data/corpus/{to_folder_name(pid)}"
                    for filename in ("metadata.json", "references.json"):
                        relative = f"{folder}/{filename}"
                        source = self.local / relative
                        if source.is_file():
                            try:
                                json.loads(source.read_text(encoding="utf-8"))
                            except ValueError:
                                continue
                            paths[relative] = source
                    for record in by_paper[pid]:
                        version = record["version"]
                        if record.get("status") not in FINAL_STATUSES:
                            continue
                        relative = f"{folder}/v{version}"
                        directory = self.local / relative
                        if not directory.is_dir() or directory.is_symlink():
                            raise ValueError(f"Completed version directory missing: {relative}")
                        actual = set()
                        for source in directory.rglob("*"):
                            if source.is_symlink():
                                raise ValueError(f"Unsafe completed version file: {source}")
                            if source.is_file():
                                if source.suffix.lower() not in (".tex", ".bib"):
                                    raise ValueError(f"Unfiltered completed version file: {source}")
                                actual.add(source.relative_to(directory).as_posix())
                        expected = record.get("files", [])
                        if actual != set(expected) or len(expected) != len(set(expected)):
                            raise ValueError(f"Completed version file list mismatch: {relative}")
                        records.append(record)
                        directories.add(relative)
                        for filename in record.get("files", []):
                            member = f"{relative}/{filename}"
                            if not self.safe_name(member) or not (self.local / member).is_file():
                                raise ValueError(f"Completed version file missing/unsafe: {member}")
                            paths[member] = self.local / member
                if not paths and not records:
                    continue
                issues, _ = validate_range(group, self.local / "data/corpus", owner="archive",
                                           versions_log=state, require_references=True)
                complete = not any(issue.severity == "error" for issue in issues)
                for pid in group:
                    ref = self.local / f"data/corpus/{to_folder_name(pid)}/references.json"
                    if not ref.is_file():
                        complete = False
                    else:
                        try:
                            complete &= json.loads(ref.read_text(encoding="utf-8")).get("status") in ("ok", "not_found")
                        except ValueError:
                            complete = False
                description = dict(schema=1, ids=group, versions=records, provenance=provenance,
                                   complete=bool(complete), compression=dict(format="tar.gz", level=1))
                signature = rows_digest([description, {name: digest(path) for name, path in paths.items()}])
                previous = next((b for b in old.get("batches", []) if b["number"] == number), {})
                if previous.get("signature") == signature:
                    batches.append(previous)
                    continue
                result = self._pack(paths, directories, description, staging, f"batch-{number:04d}")
                copied += result["bytes"]
                packing += result["packing_verify_s"]
                uploading += result["upload_verify_s"]
                batches.append(dict(result, number=number, ids=group, papers=len(group),
                                    versions=len(records), complete=bool(complete), signature=signature))
            work_paths = {}
            for folder in (work, self.local / "book_csv"):
                for path in sorted(folder.rglob("*")):
                    relative = path.relative_to(self.local)
                    if (path.is_file() and path.name != "run.lock" and "tmp" not in relative.parts
                            and "measurements" not in relative.parts):
                        work_paths[relative.as_posix()] = path
            work_archive = self._pack(work_paths, [], dict(schema=1, provenance=provenance), staging, "work")
            copied += work_archive["bytes"]
            packing += work_archive["packing_verify_s"]
            uploading += work_archive["upload_verify_s"]
        generation = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:8]
        index = dict(schema="batch-archive-v1", generation=generation, batches=batches,
                     work_archive=work_archive, versions=sum(b["versions"] for b in batches),
                     bytes=copied, committed_at=datetime.now(UTC).isoformat(),
                     packing_verify_s=packing, upload_verify_s=uploading)
        write_json(self.remote / "indices" / f"{generation}.json", index)
        write_json(self.remote / "INDEX.json", index)
        if json.loads((self.remote / "INDEX.json").read_text(encoding="utf-8")) != index:
            raise OSError("Archive index readback failed")
        write_json(head, index)
        return index

    def restore(self):
        index = json.loads((self.remote / "INDEX.json").read_text(encoding="utf-8"))
        if index.get("schema") != "batch-archive-v1":
            raise ValueError("Wrong archive checkpoint schema")
        if self.local.exists() and any(self.local.iterdir()):
            raise FileExistsError("Restore needs a fresh local directory")
        self.local.mkdir(parents=True, exist_ok=True)
        for entry in [*index["batches"], index["work_archive"]]:
            if not self.safe_name(entry["path"]):
                raise ValueError("Unsafe archive path")
            source = self.remote / entry["path"]
            manifest = verify_batch(source, expected_sha256=entry["sha256"])
            for directory in manifest["directories"]:
                (self.local / directory).mkdir(parents=True, exist_ok=True)
            with tarfile.open(source, "r:gz") as archive:
                for name, expected in manifest["files"].items():
                    destination = self.local / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(name) as stream, destination.open("wb") as output:
                        shutil.copyfileobj(stream, output)
                    if digest(destination) != expected:
                        raise ValueError(f"Restored archive file checksum mismatch: {name}")
        write_json(self.local / ".archive-head.json", index)
        events = [json.loads(path.read_text(encoding="utf-8"))
                  for path in sorted((self.remote / "checkpoint-events").glob("*.json"))]
        (self.local / "work/checkpoint_events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        archive_events = [json.loads(path.read_text(encoding="utf-8"))
                          for path in sorted((self.remote / "archive-events").glob("*.json"))]
        (self.local / "work/archive_events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in archive_events), encoding="utf-8")
        for path in (self.remote / "sessions").glob("*.json"):
            write_json(self.local / "work/session_totals" / path.name,
                       json.loads(path.read_text(encoding="utf-8")))
        collect_measurements(self.local, self.remote)
        return index


def archive_timing_rows(work_dirs):
    """Archive diagnostics are components of checkpoint wall, never extra wall."""
    events, heads = {}, []
    for work in work_dirs:
        journal = work / "archive_events.jsonl"
        if journal.exists():
            for line in journal.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    events[row["generation"]] = row
                except (ValueError, KeyError):
                    continue
        head = work.parent / ".archive-head.json"
        if head.exists():
            heads.append(json.loads(head.read_text(encoding="utf-8")))
    if not events and not heads:
        return []
    measured = [row for row in events.values() if row["phase"] != "evidence-publication"]
    outside = [row for row in events.values() if row["phase"] == "evidence-publication"]
    tool = "archive_events.jsonl; checkpoint component already included in session wall"
    result = [dict(metric="archive_packing_verify_time", value=sum(row["packing_verify_s"] for row in measured), unit="s", tool=tool),
              dict(metric="archive_upload_verify_time", value=sum(row["upload_verify_s"] for row in measured), unit="s", tool=tool),
              dict(metric="archive_evidence_publication_time", value=sum(row["packing_verify_s"] + row["upload_verify_s"] for row in outside),
                   unit="s", tool="archive_events.jsonl; outside session sampler")]
    if heads:
        result.append(dict(metric="archive_payload_size", value=sum(batch["bytes"] for head in heads for batch in head["batches"]) / 1e6,
                           unit="MB", tool="latest batch objects only; excludes work and historical checkpoint objects"))
    return result
