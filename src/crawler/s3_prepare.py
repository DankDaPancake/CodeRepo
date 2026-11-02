"""Plan and verify Requester Pays source bundles before a crawl.

The manifest's item boundaries are a *candidate* index, not proof of version
coverage. Downloaded archives stay unchanged and are never extracted here.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Bundle:
    key: str
    first: str
    last: str
    size: int
    md5: str
    timestamp: str


def _id(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})\.(\d{4,5})(?:v\d+)?", value)
    if not match:
        raise ValueError(f"Unsupported arXiv ID: {value}")
    return int(match[1]), int(match[2])


def parse_manifest(data: bytes) -> list[Bundle]:
    root = ET.fromstring(data)
    result = []
    for node in root.iter():
        if node.tag.split("}")[-1] != "file":
            continue
        fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in node}
        key = fields["filename"]
        path = PurePosixPath(key)
        if (
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) != 2
            or path.parts[0] != "src"
            or not key.endswith(".tar")
        ):
            raise ValueError(f"Unsafe bundle key: {key}")
        md5 = fields["md5sum"].lower()
        size = int(fields["size"])
        if not re.fullmatch(r"[0-9a-f]{32}", md5) or size <= 0:
            raise ValueError(f"Invalid checksum or size for {key}")
        result.append(
            Bundle(key, fields["first_item"], fields["last_item"], size, md5, fields["timestamp"])
        )
    if not result or len({b.key for b in result}) != len(result):
        raise ValueError("Empty manifest or duplicate bundle key")
    return result


def select_bundles(bundles: list[Bundle], ids: list[str]) -> tuple[list[Bundle], list[str]]:
    wanted = [(i, _id(i)) for i in ids]
    covered: set[str] = set()
    selected = []
    for bundle in bundles:
        match = re.fullmatch(r"src/arXiv_src_(\d{4})_\d+\.tar", bundle.key)
        if not match:
            raise ValueError(f"Cannot interpret bundle month: {bundle.key}")
        if not any(f"{key[0]:04d}" == match[1] for _, key in wanted):
            continue
        try:
            first, last = _id(bundle.first), _id(bundle.last)
        except ValueError as exc:
            raise ValueError(f"Cannot safely interpret boundaries for {bundle.key}") from exc
        if first > last:
            raise ValueError(f"Reversed boundaries for {bundle.key}")
        matches = [name for name, key in wanted if first <= key <= last]
        if matches:
            selected.append(bundle)
            covered.update(matches)
    return selected, [i for i in ids if i not in covered]


def _verify(path: Path, bundle: Bundle) -> bool:
    if not path.is_file():
        return False
    digest = hashlib.md5()  # arXiv manifest provides MD5, not a security signature
    with path.open("rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == bundle.md5


def download_bundle(s3, bundle: Bundle, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / PurePosixPath(bundle.key).name
    if _verify(target, bundle):
        return {
            "key": bundle.key,
            "status": "reused",
            "bytes": target.stat().st_size,
            "manifest_bytes": bundle.size,
            "md5": bundle.md5,
            "seconds": 0.0,
        }
    if target.exists():
        raise FileExistsError(
            f"Existing bundle failed verification: {target}; inspect before replacing"
        )
    temporary = target.with_name(target.name + ".part")
    started = time.perf_counter()
    body = s3.get_object(Bucket="arxiv", Key=bundle.key, RequestPayer="requester")["Body"]
    try:
        with temporary.open("wb") as out:
            while chunk := body.read(8 * 1024 * 1024):
                out.write(chunk)
        if not _verify(temporary, bundle):
            raise ValueError(f"Bundle checksum mismatch: {bundle.key}")
        os.replace(temporary, target)
    finally:
        body.close()
    return {
        "key": bundle.key,
        "status": "downloaded",
        "bytes": target.stat().st_size,
        "manifest_bytes": bundle.size,
        "md5": bundle.md5,
        "seconds": round(time.perf_counter() - started, 3),
    }
