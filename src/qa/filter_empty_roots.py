"""Create a separate M2 output with no elements for empty versions."""

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from src.parser.writer import to_table
from src.utils.ids import to_folder_name


def filter_output(out_dir, journal, destination, on_progress=None):
    source, target = Path(out_dir).resolve(), Path(destination).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Overlapping output paths")
    if target.exists():
        raise ValueError("Destination exists")
    entries = [json.loads(line) for line in Path(journal).read_text(encoding="utf8").splitlines()]
    if not entries:
        raise ValueError("Empty journal")
    names = [f"shard-{row['shard']:05d}" for row in entries]
    if len(names) != len(set(names)) or set(names) != {p.name for p in source.glob("shard-*")}:
        raise ValueError("Shard inventory mismatch")
    target.mkdir(parents=True)
    removed = 0
    for done, (row, name) in enumerate(zip(entries, names, strict=True), 1):
        original = source / name
        dest = target / name
        dest.mkdir()
        elements = pq.read_table(original / "elements.parquet").to_pylist()
        hierarchy = pq.read_table(original / "hierarchy.parquet").to_pylist()
        by_version = defaultdict(list)
        by_element = defaultdict(list)
        references = Counter()
        for edge in hierarchy:
            by_version[(edge["arxiv_id"], edge["version"])].append(edge)
            references[edge["element_id"]] += 1
            if edge["parent_id"] != edge["element_id"]:
                references[edge["parent_id"]] += 1
        for element in elements:
            by_element[(element["arxiv_id"], element["element_id"])].append(element)
        drop = set()
        for paper in row["papers"]:
            key = to_folder_name(paper["arxiv_id"])
            for version in paper["versions"]:
                if version["status"] != "empty":
                    continue
                edges = by_version[(paper["arxiv_id"], version["version"])]
                if len(edges) != 1 or edges[0]["parent_id"] != key:
                    raise ValueError(
                        f"Unexpected empty version edges: {paper['arxiv_id']}v{version['version']}"
                    )
                eid = edges[0]["element_id"]
                matches = by_element[(paper["arxiv_id"], eid)]
                if (
                    len(matches) != 1
                    or matches[0]["kind"] != "document"
                    or matches[0]["content"] not in ("", None)
                ):
                    raise ValueError(f"Unexpected empty root: {eid}")
                if references[eid] != 1:
                    raise ValueError(f"Empty root is shared: {eid}")
                drop.add((paper["arxiv_id"], eid))
        elements = [e for e in elements if (e["arxiv_id"], e["element_id"]) not in drop]
        hierarchy = [e for e in hierarchy if (e["arxiv_id"], e["element_id"]) not in drop]
        pq.write_table(
            to_table("elements", elements), dest / "elements.parquet", compression="zstd"
        )
        pq.write_table(
            to_table("hierarchy", hierarchy), dest / "hierarchy.parquet", compression="zstd"
        )
        shutil.copy2(original / "bibtex.parquet", dest / "bibtex.parquet")
        removed += len(drop)
        if on_progress:
            on_progress(done, len(names))
    return {"removed_roots": removed, "shards": len(names)}
