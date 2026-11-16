"""Bounded-memory validation of the M2 paper partition."""

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from src.parser.model import LEAF_KINDS
from src.qa.check_tables import check_schema
from src.qa.qa_inputs import read_assignments, verify_shard
from src.utils.ids import to_folder_name


def validate_partition(
    out_dir: Path, journal: Path, batch_size: int = 4096, on_progress=None, expected_hashes=None
) -> dict[str, int]:
    """Reject rows whose paper or identifiers contradict the committed partition."""
    assignments = read_assignments(journal)
    expected = {f"shard-{n:05d}" for n in assignments.values()}
    actual = {p.name for p in Path(out_dir).glob("shard-*")}
    if expected != actual:
        raise ValueError("Shard directories differ from journal")
    if expected_hashes is not None and expected != set(expected_hashes):
        raise ValueError("Shard hash manifest differs from journal")
    if problems := check_schema(out_dir):
        raise ValueError(f"Invalid schemas: {problems[:5]}")
    columns = {
        "elements": ["arxiv_id", "element_id"],
        "hierarchy": ["arxiv_id", "element_id", "parent_id"],
        "bibtex": ["arxiv_id"],
    }
    for completed, name in enumerate(sorted(expected), 1):
        number = int(name.removeprefix("shard-"))
        if expected_hashes is not None:
            verify_shard(Path(out_dir) / name, expected_hashes[name])
        for table, fields in columns.items():
            parquet = pq.ParquetFile(Path(out_dir) / name / f"{table}.parquet")
            for batch in parquet.iter_batches(batch_size=batch_size, columns=fields):
                for row in batch.to_pylist():
                    paper = row["arxiv_id"]
                    if assignments.get(paper) != number:
                        raise ValueError(f"Paper {paper} in wrong shard: {name}")
                    key = to_folder_name(paper)
                    if table != "bibtex" and not row["element_id"].startswith(key + "#"):
                        raise ValueError(f"Element ownership mismatch: {paper}")
                    if table == "hierarchy":
                        parent = row["parent_id"]
                        if parent != key and not parent.startswith(key + "#"):
                            raise ValueError(f"parent ownership mismatch: {paper}")
        if expected_hashes is not None:
            verify_shard(Path(out_dir) / name, expected_hashes[name])
        if on_progress:
            on_progress(completed, len(expected))
    return assignments


def check_paper(paper, elements, edges, bibkeys, expected_versions):
    """Check one isolated paper; inputs must already be ownership-validated."""
    problems = []
    children = defaultdict(list)
    roots = defaultdict(list)
    parents = defaultdict(set)
    used = set()
    seen = set()
    version_parents = defaultdict(set)
    versions = set(expected_versions)
    for version, eid, parent in edges:
        if version not in expected_versions:
            problems.append(f"unexpected version: {version}")
        versions.add(version)
        edge = (version, eid, parent)
        if edge in seen:
            problems.append(f"duplicate edge: {edge}")
        seen.add(edge)
        version_parents[(version, eid)].add(parent)
        used.add(eid)
        if eid not in elements:
            problems.append(f"missing element: {eid}")
            continue
        if parent == paper:
            roots[version].append(eid)
            if elements[eid] != "document":
                problems.append(f"invalid root kind: {eid}")
        elif parent not in elements:
            problems.append(f"missing parent: {parent}")
        else:
            if elements[parent] in LEAF_KINDS:
                problems.append(f"leaf parent has children: {parent}")
            children[(version, parent)].append(eid)
        if elements[eid] not in LEAF_KINDS | {"document"}:
            parents[eid].add("<document>" if elements.get(parent) == "document" else parent)
    for key, count in Counter(bibkeys).items():
        if count > 1:
            problems.append(f"duplicate bibtex key: {key}")
    for eid, values in parents.items():
        if len(values) > 1:
            problems.append(f"branch has multiple parents: {eid}")
    for (version, eid), values in version_parents.items():
        if len(values) > 1 and elements.get(eid) not in LEAF_KINDS:
            problems.append(f"version {version}: multiple parents for {eid}")
    for version in versions:
        if len(roots[version]) != 1:
            problems.append(f"version {version}: {len(roots[version])} roots")
        visited = set()
        stack = list(roots[version])
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(children[(version, node)])
        nodes = {eid for ver, eid, _ in edges if ver == version}
        if nodes - visited:
            problems.append(f"version {version}: {len(nodes - visited)} unreachable nodes")
        colors = {}
        for start in nodes:
            if colors.get(start, 0):
                continue
            stack = [(start, False)]
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    colors[node] = 2
                    continue
                if colors.get(node) == 1:
                    problems.append(f"version {version}: cycle at {node}")
                    continue
                if colors.get(node) == 2:
                    continue
                colors[node] = 1
                stack.append((node, True))
                stack.extend((child, False) for child in children[(version, node)])
    if unused := set(elements) - used:
        problems.append(f"{len(unused)} unused elements")
    return problems


def check_run(
    out_dir: Path,
    journal: Path,
    *,
    max_shard_rows: int = 500_000,
    on_progress=None,
    on_validation=None,
    checkpoint_dir: Path | None = None,
    identity: dict | None = None,
    expected_hashes: dict | None = None,
    empty_without_root: bool = False,
) -> dict:
    """Check the committed partition with a hard cap on each shard's loaded rows."""
    assignments = validate_partition(
        out_dir, journal, on_progress=on_validation, expected_hashes=expected_hashes
    )
    records = {}
    for line in Path(journal).read_text(encoding="utf8").splitlines():
        shard = json.loads(line)
        for paper in shard["papers"]:
            seen_versions = set()
            for version in paper["versions"]:
                number = version["version"]
                if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                    raise ValueError("Invalid journal version number")
                if number in seen_versions:
                    raise ValueError("Duplicate journal version")
                seen_versions.add(number)
                if version["status"] not in {"parsed", "empty", "no_root", "missing", "error"}:
                    raise ValueError("Invalid journal version status")
            records[paper["arxiv_id"]] = paper
    errors = []
    error_count = 0
    totals = Counter()
    elements_by_kind = Counter()
    versions = 0
    numbers = sorted(set(assignments.values()))
    if checkpoint_dir is not None:
        if not identity:
            raise ValueError("Checkpoint identity is required")
        checkpoint_dir = Path(checkpoint_dir)
        source = Path(out_dir).resolve()
        if checkpoint_dir.resolve() == source or checkpoint_dir.resolve().is_relative_to(source):
            raise ValueError("Checkpoint directory overlaps input")
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "identity": identity,
            "journal_sha256": hashlib.sha256(Path(journal).read_bytes()).hexdigest(),
            "max_shard_rows": max_shard_rows,
            "version": 2,
            "empty_without_root": empty_without_root,
        }
        meta_path = checkpoint_dir / "identity.json"
        if meta_path.exists():
            if json.loads(meta_path.read_text(encoding="utf8")) != metadata:
                raise ValueError("Checkpoint identity changed")
        else:
            if any(checkpoint_dir.glob("shard-*.json")):
                raise ValueError("Checkpoint identity missing")
            temp = meta_path.with_suffix(".part")
            temp.write_text(json.dumps(metadata, sort_keys=True), encoding="utf8")
            os.replace(temp, meta_path)
    for completed, number in enumerate(numbers, 1):
        path = Path(out_dir) / f"shard-{number:05d}"
        if expected_hashes is not None:
            verify_shard(path, expected_hashes[path.name])
        columns = {
            "elements": ["arxiv_id", "element_id", "kind"],
            "hierarchy": ["arxiv_id", "version", "element_id", "parent_id"],
            "bibtex": ["arxiv_id", "citation_key"],
        }
        counts = {k: pq.ParquetFile(path / f"{k}.parquet").metadata.num_rows for k in columns}
        if sum(counts.values()) > max_shard_rows:
            raise ValueError(f"Shard row limit exceeded: {path.name}")
        shard_hashes = {}
        if checkpoint_dir is not None:
            for table in columns:
                with (path / f"{table}.parquet").open("rb") as stream:
                    shard_hashes[table] = hashlib.file_digest(stream, "sha256").hexdigest()
            checkpoint = checkpoint_dir / f"{path.name}.json"
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text(encoding="utf8"))
                if saved["hashes"] != shard_hashes or saved["rows"] != counts:
                    raise ValueError(f"Checkpoint input changed: {path.name}")
                totals.update(saved["rows"])
                elements_by_kind.update(dict(saved["elements_by_kind"]))
                versions += saved["versions"]
                error_count += saved["n_problems"]
                errors.extend(saved["problems"][: max(0, 50 - len(errors))])
                if on_progress:
                    on_progress(completed, len(numbers))
                continue
        previous_errors, previous_versions = error_count, versions
        shard_errors = []
        grouped = defaultdict(lambda: {"elements": {}, "edges": [], "bibkeys": []})
        duplicates = []
        shard_kinds = Counter()
        for table, fields in columns.items():
            for batch in pq.ParquetFile(path / f"{table}.parquet").iter_batches(
                batch_size=4096, columns=fields
            ):
                for row in batch.to_pylist():
                    group = grouped[row["arxiv_id"]]
                    if table == "elements":
                        shard_kinds[row["kind"]] += 1
                        eid = row["element_id"]
                        if eid in group["elements"]:
                            duplicates.append(f"duplicate element: {eid}")
                        group["elements"][eid] = row["kind"]
                    elif table == "hierarchy":
                        group["edges"].append((row["version"], row["element_id"], row["parent_id"]))
                    else:
                        group["bibkeys"].append(row["citation_key"])
        totals.update(counts)
        elements_by_kind.update(shard_kinds)
        shard_papers = [paper for paper, shard in assignments.items() if shard == number]
        for paper in shard_papers:
            group = grouped[paper]
            expected_versions = {
                item["version"]
                for item in records[paper]["versions"]
                if item["status"] != "missing"
                and not (empty_without_root and item["status"] == "empty")
            }
            versions += len({edge[0] for edge in group["edges"]})
            found = check_paper(to_folder_name(paper), **group, expected_versions=expected_versions)
            if records[paper].get("error"):
                found.append(f"paper failed: {paper}: {str(records[paper]['error'])[:300]}")
            for item in records[paper]["versions"]:
                if item["status"] == "error":
                    found.append(f"version failed: {paper}v{item['version']}")
            error_count += len(found)
            shard_errors.extend(found[: max(0, 50 - len(shard_errors))])
        error_count += len(duplicates)
        shard_errors.extend(duplicates[: max(0, 50 - len(shard_errors))])
        errors.extend(shard_errors[: max(0, 50 - len(errors))])
        if expected_hashes is not None:
            verify_shard(path, expected_hashes[path.name])
        if checkpoint_dir is not None:
            saved = {
                "hashes": shard_hashes,
                "rows": counts,
                "elements_by_kind": list(shard_kinds.items()),
                "versions": versions - previous_versions,
                "n_problems": error_count - previous_errors,
                "problems": shard_errors,
            }
            temp = checkpoint.with_suffix(".part")
            temp.write_text(json.dumps(saved, sort_keys=True), encoding="utf8")
            os.replace(temp, checkpoint)
        if on_progress:
            on_progress(completed, len(numbers))
    return {
        "ok": error_count == 0,
        "n_problems": error_count,
        "problems": errors,
        "rows": dict(totals),
        "elements_by_kind": dict(elements_by_kind),
        "papers": len(assignments),
        "versions": versions,
    }
