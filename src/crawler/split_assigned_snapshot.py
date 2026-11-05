"""Create reproducible version-group snapshots for the 20,000 assigned IDs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from src import config
from src.crawler.s3_partition import partition_snapshot
from src.crawler.snapshot import sha256
from src.utils.ids import iter_id_range


def split_snapshot(source: Path, output: Path) -> dict:
    """Copy original JSONL records; refuse to overwrite or accept invalid coverage."""
    names = ("arxiv-assigned-20000.jsonl", "arxiv-assigned-only-v1.jsonl",
             "arxiv-assigned-multi-version.jsonl")
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in names):
        raise FileExistsError("Output files already exist; select a new directory")
    wanted = {pid for a, b in config.RANGES.values()
              for pid in iter_id_range(a, b, config.MONTH_END)}
    pattern = re.compile(rb'"id"\s*:\s*"([^"\\]+)"')
    found = set()
    full = output / names[0]
    with source.open("rb") as source_file, full.open("xb") as target:
        for line in source_file:
            match = pattern.search(line)
            pid = match.group(1).decode("ascii", "ignore") if match else None
            if pid in wanted:
                if pid in found:
                    raise ValueError(f"Duplicate snapshot ID: {pid}")
                found.add(pid)
                target.write(line if line.endswith(b"\n") else line + b"\n")
    if found != wanted:
        raise ValueError(f"Snapshot missing {len(wanted - found)} assigned IDs")
    groups = partition_snapshot(full, sorted(wanted))
    if groups.missing:
        raise ValueError(f"Snapshot has {len(groups.missing)} invalid IDs")
    result = {}
    for name, ids in zip(names[1:], (set(groups.only_v1), set(groups.multi_version)), strict=True):
        path = output / name
        with full.open("rb") as source_file, path.open("xb") as target:
            for line in source_file:
                match = pattern.search(line)
                if match and match.group(1).decode("ascii", "ignore") in ids:
                    target.write(line)
        result[name] = dict(papers=len(ids), bytes=path.stat().st_size, sha256=sha256(path))
    result[names[0]] = dict(papers=len(found), bytes=full.stat().st_size, sha256=sha256(full))
    return result


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(split_snapshot(args.source, args.output), indent=2))


if __name__ == "__main__":
    main()
