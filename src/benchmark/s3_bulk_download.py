"""Plan and stage S3 bulk downloads without touching crawler run directories."""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

import psutil

from src.crawler.s3_prepare import _id, _verify


class ResourceSampler:
    """Sample process-tree RSS and the local stage directory; peaks are lower bounds."""

    def __init__(self, stage: Path, interval_s: float = 2.0):
        self.stage, self.interval_s = stage, interval_s
        self.peak_rss_bytes = self.peak_stage_bytes = None
        self.samples = 0
        self.errors = []
        self.stop = threading.Event()

    def sample(self):
        try:
            process = psutil.Process()
            rss = sum(
                p.memory_info().rss
                for p in [process, *process.children(recursive=True)]
                if p.is_running()
            )
            stage_bytes = sum(
                path.stat().st_size for path in self.stage.rglob("*") if path.is_file()
            )
            self.peak_rss_bytes = max(self.peak_rss_bytes or 0, rss)
            self.peak_stage_bytes = max(self.peak_stage_bytes or 0, stage_bytes)
            self.samples += 1
        except (OSError, psutil.Error) as exc:
            self.errors.append(type(exc).__name__)

    def __enter__(self):
        self.sample()

        def run():
            while not self.stop.wait(self.interval_s):
                self.sample()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.sample()


def validate_snapshot(path: Path, ids: list[str]) -> dict:
    if len(set(ids)) != len(ids) or not ids:
        raise ValueError("duplicate or empty assigned IDs")
    expected, seen = set(ids), set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            pid = json.loads(line)["id"]
            if pid in seen:
                raise ValueError(f"duplicate snapshot ID: {pid}")
            seen.add(pid)
    missing, extra = expected - seen, seen - expected
    if missing or extra:
        raise ValueError(f"snapshot mismatch: {len(missing)} missing, {len(extra)} extra IDs")
    return {"papers": len(seen), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def plan_candidates(bundles, ids: list[str]):
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("duplicate or empty IDs")
    ordered = sorted((_id(pid), pid) for pid in ids)
    keys = [x[0] for x in ordered]
    mapping = {pid: [] for pid in ids}
    selected = []
    for item in bundles:
        month = re.fullmatch(r"src/arXiv_src_(\d{4})_\d+\.tar", item.key)
        if not month:
            raise ValueError(f"Unsupported bundle key: {item.key}")

        # arXiv starts in 1991: 91–99 are 1900s, whereas modern IDs use 2000s.
        def chronological(yymm):
            year, month_number = divmod(int(yymm), 100)
            if not 1 <= month_number <= 12:
                raise ValueError(f"Invalid arXiv month: {yymm}")
            return (1900 if year >= 91 else 2000) * 100 + year * 100 + month_number

        # A bundle published before the ID's submission month cannot contain it.
        if chronological(month[1]) < chronological(keys[0][0]):
            continue
        first, last = _id(item.first), _id(item.last)
        if first > last:
            raise ValueError(f"Reversed bundle boundaries: {item.key}")
        start, stop = bisect.bisect_left(keys, first), bisect.bisect_right(keys, last)
        if start != stop:
            selected.append(item)
            for _, pid in ordered[start:stop]:
                mapping[pid].append(item.key)
    return selected, mapping, [pid for pid in ids if not mapping[pid]]


def transfer_bundle(s3, bundle, local: Path, destination: Path, progress=None) -> dict:
    """Stage and verify locally before copying to Drive; never overwrite existing files."""
    local.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / Path(bundle.key).name
    if target.exists():
        if not _verify(target, bundle):
            raise FileExistsError(f"Existing bundle failed MD5: {target}")
        return dict(
            key=bundle.key,
            status="reused",
            bytes=target.stat().st_size,
            manifest_bytes=bundle.size,
            download_s=None,
            verify_local_s=None,
            copy_to_drive_s=None,
            download_bytes_per_s=None,
        )
    with tempfile.TemporaryDirectory(prefix="s3-stage-", dir=local) as tmp:
        staged = Path(tmp) / target.name
        start = time.perf_counter()
        body = s3.get_object(Bucket="arxiv", Key=bundle.key, RequestPayer="requester")["Body"]
        try:
            with staged.open("xb") as out:
                while chunk := body.read(8 * 1024 * 1024):
                    out.write(chunk)
                    if progress:
                        progress(len(chunk))
        finally:
            body.close()
        download_s = time.perf_counter() - start
        start = time.perf_counter()
        if not _verify(staged, bundle):
            raise ValueError(f"Bundle MD5 mismatch: {bundle.key}")
        verify_s = time.perf_counter() - start
        size = staged.stat().st_size
        start = time.perf_counter()
        # Named temporary output is not considered a published bundle.
        with tempfile.NamedTemporaryFile(
            prefix=target.name + ".", suffix=".part", dir=destination, delete=False
        ) as out:
            temporary = Path(out.name)
        try:
            with temporary.open("wb") as out:
                with staged.open("rb") as source:
                    shutil.copyfileobj(source, out, 8 * 1024 * 1024)
            if target.exists():
                raise FileExistsError(f"Destination appeared while copying: {target}")
            temporary.rename(target)
        finally:
            temporary.unlink(missing_ok=True)
        return dict(
            key=bundle.key,
            status="downloaded",
            bytes=size,
            manifest_bytes=bundle.size,
            download_s=download_s,
            verify_local_s=verify_s,
            copy_to_drive_s=time.perf_counter() - start,
            download_bytes_per_s=size / download_s if download_s > 0 else None,
        )
