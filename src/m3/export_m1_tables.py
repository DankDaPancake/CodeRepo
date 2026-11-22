# Drafted with the help of an AI assistant (Gemini, Google), cited per the course rules.
"""Export Milestone 1 ``papers`` and ``references`` tables as sharded zstd Parquet.

    python -m src.m3.export_m1_tables --corpus-dir data/corpus --out-dir m1_tables

Follows the exact Milestone 1 / Milestone 3 dataset schema (``docs/data_contract.md`` §6):

- ``papers``: ``arxiv_id`` (non-null), ``title``, ``authors`` (list<string>),
  ``submission_date``, ``revised_dates`` (list<string>), ``venue``.
- ``references``: ``arxiv_id`` (non-null, citing paper), ``ref_arxiv_id`` (non-null),
  ``ref_title``, ``ref_authors`` (list<string>), ``ref_submission_date``, ``ref_s2_id``.
  Only crawled references carrying a non-null arXiv ID are emitted, deduplicated per citing
  paper in original order.

Processes papers in bounded-memory shards (``--shard-papers``, default 500) so 20,000 papers
run comfortably inside a 13 GB Google Colab CPU runtime.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.config import RANGES
from src.m3.labels import range_owner
from src.utils.ids import FOLDER_RE, from_folder_name

COMPRESSION = "zstd"

SCHEMAS: dict[str, pa.Schema] = {
    "papers": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            pa.field("title", pa.string(), nullable=True),
            pa.field("authors", pa.list_(pa.string()), nullable=True),
            pa.field("submission_date", pa.string(), nullable=True),
            pa.field("revised_dates", pa.list_(pa.string()), nullable=True),
            pa.field("venue", pa.string(), nullable=True),
        ]
    ),
    "references": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            pa.field("ref_arxiv_id", pa.string(), nullable=False),
            pa.field("ref_title", pa.string(), nullable=True),
            pa.field("ref_authors", pa.list_(pa.string()), nullable=True),
            pa.field("ref_submission_date", pa.string(), nullable=True),
            pa.field("ref_s2_id", pa.string(), nullable=True),
        ]
    ),
}


def _opt_str(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _str_list(values) -> list[str]:
    if not values:
        return []
    return [str(v) for v in values if v is not None]


def paper_row_from_metadata(arxiv_id: str, meta: dict) -> dict:
    """Map one ``metadata.json`` payload to a flat ``papers`` table row."""
    pid = _opt_str(meta.get("arxiv_id")) or arxiv_id
    return {
        "arxiv_id": pid,
        "title": _opt_str(meta.get("title")),
        "authors": _str_list(meta.get("authors")),
        "submission_date": _opt_str(meta.get("submission_date")),
        "revised_dates": _str_list(meta.get("revised_dates")),
        "venue": _opt_str(meta.get("venue")),
    }


def reference_rows_from_json(arxiv_id: str, payload: dict) -> list[dict]:
    """Map one ``references.json`` payload to deduplicated arXiv-keyed ``references`` rows."""
    refs = payload.get("references") or []
    seen: set[str] = set()
    rows: list[dict] = []
    for ref in refs:
        raw_id = ref.get("arxiv_id")
        if raw_id is None:
            continue
        ref_id = str(raw_id).strip()
        if not ref_id or ref_id in seen:
            continue
        seen.add(ref_id)
        rows.append(
            {
                "arxiv_id": arxiv_id,
                "ref_arxiv_id": ref_id,
                "ref_title": _opt_str(ref.get("title")),
                "ref_authors": _str_list(ref.get("authors")),
                "ref_submission_date": _opt_str(ref.get("submission_date")),
                "ref_s2_id": _opt_str(ref.get("s2_id")),
            }
        )
    return rows


def to_table(name: str, rows: list[dict]) -> pa.Table:
    """Convert rows to a PyArrow table matching the M1/M3 statement schema."""
    schema = SCHEMAS[name]
    columns = [pa.array([row.get(f.name) for row in rows], type=f.type) for f in schema]
    return pa.Table.from_arrays(columns, schema=schema)


def _write_shard(table_name: str, rows: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(to_table(table_name, rows), tmp, compression=COMPRESSION)
    tmp.replace(path)
    return len(rows)


def discover_paper_dirs(
    corpus_dirs: list[Path],
    *,
    only_range: str | None = None,
    assigned_only: bool = False,
) -> list[tuple[str, Path]]:
    """Return sorted ``(arxiv_id, paper_dir)`` pairs across one or more M1 corpus roots."""
    by_id: dict[str, Path] = {}
    for root in corpus_dirs:
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"corpus directory not found: {root}")
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or not FOLDER_RE.match(entry.name):
                continue
            pid = from_folder_name(entry.name)
            owner = range_owner(pid)
            if only_range and owner != only_range:
                continue
            if assigned_only and owner is None:
                continue
            # Prefer a folder that actually has metadata.json if duplicated across roots.
            prev = by_id.get(pid)
            if prev is None or (
                not (prev / "metadata.json").is_file() and (entry / "metadata.json").is_file()
            ):
                by_id[pid] = entry
    return sorted(by_id.items(), key=lambda item: item[0])


def _export_group(
    papers: list[tuple[str, Path]],
    out_root: Path,
    *,
    shard_papers: int,
    use_data_prefix: bool,
) -> dict:
    base = out_root / "data" if use_data_prefix else out_root
    papers_dir = base / "papers"
    refs_dir = base / "references"

    stats = {
        "papers_total": len(papers),
        "papers_written": 0,
        "references_written": 0,
        "missing_metadata": 0,
        "missing_references": 0,
        "shards": 0,
    }
    if not papers:
        # Still emit empty schema-conformant shards so downstream HF loaders never fail.
        _write_shard("papers", [], papers_dir / "part-00000.parquet")
        _write_shard("references", [], refs_dir / "part-00000.parquet")
        stats["shards"] = 1
        return stats

    shard_idx = 0
    for start in range(0, len(papers), shard_papers):
        batch = papers[start : start + shard_papers]
        paper_rows: list[dict] = []
        ref_rows: list[dict] = []
        for pid, folder in batch:
            meta_path = folder / "metadata.json"
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                paper_rows.append(paper_row_from_metadata(pid, meta))
            else:
                stats["missing_metadata"] += 1

            ref_path = folder / "references.json"
            if ref_path.is_file():
                payload = json.loads(ref_path.read_text(encoding="utf-8"))
                ref_rows.extend(reference_rows_from_json(pid, payload))
            else:
                stats["missing_references"] += 1

        shard_name = f"part-{shard_idx:05d}.parquet"
        stats["papers_written"] += _write_shard("papers", paper_rows, papers_dir / shard_name)
        stats["references_written"] += _write_shard("references", ref_rows, refs_dir / shard_name)
        shard_idx += 1

    stats["shards"] = shard_idx
    return stats


def export_m1_tables(
    corpus_dirs: list[Path],
    out_dir: Path,
    *,
    shard_papers: int = 500,
    only_range: str | None = None,
    assigned_only: bool = False,
    split_by_range: bool = False,
    use_data_prefix: bool = True,
) -> dict:
    """Export M1 ``papers`` and ``references`` Parquet shards and return summary statistics."""
    if shard_papers <= 0:
        raise ValueError("shard_papers must be positive")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    discovered = discover_paper_dirs(
        corpus_dirs, only_range=only_range, assigned_only=assigned_only or split_by_range
    )

    if split_by_range:
        grouped: dict[str, list[tuple[str, Path]]] = defaultdict(list)
        for pid, folder in discovered:
            owner = range_owner(pid)
            if owner:
                grouped[owner].append((pid, folder))
        owners = [only_range] if only_range else sorted(RANGES)
        per_range = {}
        for owner in owners:
            per_range[owner] = _export_group(
                grouped.get(owner, []),
                out_dir / owner,
                shard_papers=shard_papers,
                use_data_prefix=use_data_prefix,
            )
        summary = {
            "mode": "split_by_range",
            "use_data_prefix": use_data_prefix,
            "ranges": per_range,
            "papers_written": sum(s["papers_written"] for s in per_range.values()),
            "references_written": sum(s["references_written"] for s in per_range.values()),
        }
    else:
        overall = _export_group(
            discovered,
            out_dir,
            shard_papers=shard_papers,
            use_data_prefix=use_data_prefix,
        )
        summary = {
            "mode": "combined",
            "use_data_prefix": use_data_prefix,
            **overall,
        }

    (out_dir / "export_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--corpus-dir",
        type=Path,
        nargs="+",
        required=True,
        help="one or more M1 corpus directories holding <yymm-num>/{metadata,references}.json",
    )
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--shard-papers", type=int, default=500)
    p.add_argument("--range", dest="only_range", choices=sorted(RANGES))
    p.add_argument(
        "--assigned-only",
        action="store_true",
        help="keep only papers inside the four assigned ranges in src/config.py",
    )
    p.add_argument(
        "--split-by-range",
        action="store_true",
        help="write separate <out-dir>/<owner>/data/{papers,references}/ shards per member",
    )
    p.add_argument(
        "--no-data-prefix",
        action="store_true",
        help="write directly under <out-dir>/{papers,references}/ instead of data/",
    )
    a = p.parse_args(argv)
    summary = export_m1_tables(
        a.corpus_dir,
        a.out_dir,
        shard_papers=a.shard_papers,
        only_range=a.only_range,
        assigned_only=a.assigned_only,
        split_by_range=a.split_by_range,
        use_data_prefix=not a.no_data_prefix,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
