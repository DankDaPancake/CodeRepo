"""Partition assigned IDs by version count in one pinned snapshot."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.crawler.discovery import parse_snapshot_line


@dataclass(frozen=True)
class Partition:
    only_v1: list[str]
    multi_version: list[str]
    missing: list[str]


def partition_snapshot(snapshot: Path, ids: list[str]) -> Partition:
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate requested ID")
    wanted = set(ids)
    found = {}
    seen = set()
    pattern = re.compile(r'"id"\s*:\s*"([^"\\]+)"')
    with snapshot.open(encoding="utf-8") as stream:
        for line in stream:
            match = pattern.search(line)
            if match is None or match[1] not in wanted:
                continue
            pid = match[1]
            if pid in seen:
                raise ValueError(f"duplicate snapshot ID: {pid}")
            seen.add(pid)
            try:
                raw = json.loads(line)
                numbers = [int(v["version"].removeprefix("v")) for v in raw["versions"]]
                record = parse_snapshot_line(line)
                if not numbers or sorted(numbers) != list(range(1, len(numbers) + 1)):
                    continue
                if not record["title"] or not record["authors"]:
                    continue
                found[pid] = len(numbers)
            except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
                continue
    return Partition(
        only_v1=[pid for pid in ids if found.get(pid) == 1],
        multi_version=[pid for pid in ids if found.get(pid, 0) > 1],
        missing=[pid for pid in ids if pid not in found],
    )
