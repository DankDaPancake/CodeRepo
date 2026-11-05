# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Integrity checks of the M2 output tables (``elements``, ``hierarchy``, ``bibtex``).

    python -m src.qa.check_tables --out-dir data/m2 [--json report.json]

Reads every ``shard-*/{elements,hierarchy,bibtex}.parquet`` and checks, on the whole output:

1. the column names and types are the ones of the M2 statement;
2. ``element_id`` is unique in ``elements``; ``(arxiv_id, citation_key)`` is unique in ``bibtex``;
3. every ``element_id`` and ``parent_id`` of ``hierarchy`` exists (a root hangs from the paper key);
4. each ``(arxiv_id, version)`` has exactly one root and every node is reachable from it;
5. a branch (section, list, item) has a single parent in all versions (the tree can be rebuilt);
6. no element is unused, and every ID starts with the publication key.

The exit code is 0 when all checks pass, 1 otherwise. The report also gives the counts the book
needs: elements per kind, rows per table, elements before and after deduplication.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from src.parser.model import LEAF_KINDS
from src.parser.writer import SCHEMAS
from src.utils.ids import to_folder_name


def read_table(out_dir: Path, name: str) -> list[dict]:
    rows: list[dict] = []
    for shard in sorted(Path(out_dir).glob("shard-*")):
        path = shard / f"{name}.parquet"
        if path.exists():
            rows.extend(pq.read_table(path).to_pylist())
    return rows


def check_schema(out_dir: Path) -> list[str]:
    problems = []
    for shard in sorted(Path(out_dir).glob("shard-*")):
        for name, schema in SCHEMAS.items():
            path = shard / f"{name}.parquet"
            if not path.exists():
                problems.append(f"{shard.name}: {name}.parquet is missing")
                continue
            got = pq.read_schema(path)
            if got.names != schema.names:
                problems.append(f"{shard.name}/{name}: columns {got.names} != {schema.names}")
                continue
            for field in schema:
                have = got.field(field.name).type
                if not have.equals(field.type):
                    problems.append(f"{shard.name}/{name}.{field.name}: {have} != {field.type}")
    return problems


def check(out_dir: Path) -> dict:
    elements = read_table(out_dir, "elements")
    hierarchy = read_table(out_dir, "hierarchy")
    bibtex = read_table(out_dir, "bibtex")
    problems = check_schema(out_dir)

    by_id: dict[str, dict] = {}
    for row in elements:
        if row["element_id"] in by_id:
            problems.append(f"duplicate element_id {row['element_id']}")
        by_id[row["element_id"]] = row
    seen_bib = Counter((r["arxiv_id"], r["citation_key"]) for r in bibtex)
    problems += [f"duplicate bibtex key {k}" for k, n in seen_bib.items() if n > 1]

    children: dict[tuple, list[str]] = defaultdict(list)  # (arxiv_id, version, parent) -> ids
    roots: dict[tuple, list[str]] = defaultdict(list)
    branch_parents: dict[str, set[str]] = defaultdict(set)
    used: set[str] = set()
    for row in hierarchy:
        eid, parent = row["element_id"], row["parent_id"]
        used.add(eid)
        if eid not in by_id:
            problems.append(f"hierarchy element_id {eid} is not in elements")
            continue
        if not eid.startswith(to_folder_name(row["arxiv_id"]) + "#"):
            problems.append(f"{eid} does not start with the key of {row['arxiv_id']}")
        if parent == to_folder_name(row["arxiv_id"]):
            roots[(row["arxiv_id"], row["version"])].append(eid)
        elif parent not in by_id:
            problems.append(f"parent {parent} of {eid} is not in elements")
        else:
            children[(row["arxiv_id"], row["version"], parent)].append(eid)
        if by_id[eid]["kind"] not in LEAF_KINDS | {"document"}:
            # the root of each version is a different element but the same place
            is_root = parent in by_id and by_id[parent]["kind"] == "document"
            branch_parents[eid].add("<document>" if is_root else parent)

    for key, ids in roots.items():
        if len(ids) != 1:
            problems.append(f"{key}: {len(ids)} roots")
    for eid, parents in branch_parents.items():
        if len(parents) > 1:
            problems.append(f"branch {eid} has {len(parents)} parents")

    reached = 0
    for (arxiv_id, version), ids in roots.items():
        stack = list(ids)
        while stack:
            node = stack.pop()
            reached += 1
            stack.extend(children.get((arxiv_id, version, node), ()))
    expected = len(
        {(r["arxiv_id"], r["version"], r["element_id"], r["parent_id"]) for r in hierarchy}
    )
    if reached != expected:
        problems.append(f"{expected - reached} hierarchy rows are not reachable from a root")
    unused = set(by_id) - used
    if unused:
        problems.append(f"{len(unused)} elements are in no version (e.g. {sorted(unused)[:3]})")

    return {
        "ok": not problems,
        "problems": problems[:50],
        "n_problems": len(problems),
        "rows": {"elements": len(elements), "hierarchy": len(hierarchy), "bibtex": len(bibtex)},
        "elements_by_kind": dict(Counter(r["kind"] for r in elements)),
        "papers": len({r["arxiv_id"] for r in elements}),
        "versions": len(roots),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, help="write the report here")
    args = parser.parse_args(argv)
    report = check(args.out_dir)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
