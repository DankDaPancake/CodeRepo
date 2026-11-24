# Drafted with the help of an AI assistant (Gemini, Google), cited per the course rules.
"""Assemble Milestone 3 six-table Parquet packages for Hugging Face with bounded memory.

    python -m src.m3.package_dataset --m1-dir m1_tables_by_range --m2-dir M2_OUT \
        --predictions-dir predictions_by_range --out-dir packages --mode by-range

Produces the exact Milestone 3 dataset repository layout::

    <out-dir>/<owner>/
      README.md                (dataset card YAML configs, no loading script)
      package_summary.json
      data/
        papers/*.parquet
        references/*.parquet
        elements/*.parquet
        hierarchy/*.parquet
        bibtex/*.parquet
        predictions/*.parquet

Memory safety: M2 tables (``elements`` ~9.2M rows, ``hierarchy`` ~11.7M rows, ``bibtex``
~0.84M rows) are streamed one ``shard-*/`` at a time, filtered with PyArrow compute
(``pc.is_in``), and flushed whenever a range buffer reaches ``--target-rows``. Supports
``--allow-missing-predictions`` to pre-package the 5 M1+M2 tables while the model is being
trained, then re-run once ``predictions`` lands.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from src.config import RANGES
from src.m3 import hf_dataset
from src.m3.labels import range_owner
from src.parser.writer import COMPRESSION as M2_COMPRESSION
from src.parser.writer import SCHEMAS as M2_SCHEMAS

M1_TABLES = ("papers", "references")
M2_TABLES = ("elements", "hierarchy", "bibtex")
DEFAULT_TARGET_ROWS = {
    "elements": 500_000,
    "hierarchy": 500_000,
    "bibtex": 100_000,
}


def _clean_parquet_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.parquet"):
        old.unlink()


def _resolve_table_shards(root: Path, owner: str | None, table_name: str) -> list[Path]:
    """Locate Parquet shards under ``<root>/<owner>/data/<table>`` or flat fallbacks."""
    candidates: list[Path] = []
    if owner is not None:
        candidates.extend(
            [
                root / owner / "data" / table_name,
                root / owner / table_name,
            ]
        )
    candidates.extend([root / "data" / table_name, root / table_name])
    for folder in candidates:
        files = sorted(folder.glob("*.parquet"))
        if files:
            return files
    return []


def _copy_shards(sources: list[Path], dest_dir: Path) -> tuple[int, int]:
    """Copy Parquet shards sequentially into ``dest_dir/part-NNNNN.parquet``."""
    _clean_parquet_dir(dest_dir)
    total_rows = 0
    for idx, src in enumerate(sources):
        dest = dest_dir / f"part-{idx:05d}.parquet"
        tmp = dest.with_suffix(".parquet.tmp")
        shutil.copyfile(src, tmp)
        tmp.replace(dest)
        total_rows += pq.ParquetFile(dest).metadata.num_rows
    return len(sources), total_rows


def _flush_arrow_buffer(
    table_name: str,
    chunks: list[pa.Table],
    dest_dir: Path,
    shard_idx: int,
) -> int:
    schema = M2_SCHEMAS[table_name]
    if chunks:
        combined = pa.concat_tables(chunks, promote_options="none")
        # Unify dictionary chunks across shards so each output file has a clean single dictionary.
        cols = []
        for field in schema:
            col = combined.column(field.name)
            if pa.types.is_dictionary(field.type):
                col = col.combine_chunks().dictionary_encode()
            cols.append(col)
        table = pa.Table.from_arrays(cols, schema=schema)
    else:
        cols = []
        for field in schema:
            if pa.types.is_dictionary(field.type):
                cols.append(pa.array([], type=pa.string()).dictionary_encode())
            else:
                cols.append(pa.array([], type=field.type))
        table = pa.Table.from_arrays(cols, schema=schema)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"part-{shard_idx:05d}.parquet"
    tmp = dest.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression=M2_COMPRESSION)
    tmp.replace(dest)
    return table.num_rows


def split_m2_tables(
    m2_dir: Path,
    out_dir: Path,
    *,
    mode: str = "by-range",
    owners: list[str] | None = None,
    target_rows: dict[str, int] | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """Stream M2 ``shard-*/{elements,hierarchy,bibtex}.parquet`` into target packages."""
    shard_dirs = sorted(p for p in Path(m2_dir).glob("shard-*") if p.is_dir())
    if not shard_dirs:
        raise FileNotFoundError(f"no shard-* directories under {m2_dir}")

    limits = {**DEFAULT_TARGET_ROWS, **(target_rows or {})}
    if mode == "combined":
        summary: dict[str, dict[str, int]] = {}
        for tname in M2_TABLES:
            dest_dir = out_dir / "all" / "data" / tname
            sources = [
                sd / f"{tname}.parquet" for sd in shard_dirs if (sd / f"{tname}.parquet").is_file()
            ]
            if not sources:
                raise FileNotFoundError(f"no {tname}.parquet shards under {m2_dir}")
            n_shards, n_rows = _copy_shards(sources, dest_dir)
            summary[tname] = {"shards": n_shards, "rows": n_rows}
        return {"all": summary}

    target_owners = sorted(owners) if owners else sorted(RANGES)
    wanted_set = set(target_owners)
    stats: dict[str, dict[str, dict[str, int]]] = {
        o: {t: {"shards": 0, "rows": 0} for t in M2_TABLES} for o in target_owners
    }

    for owner in target_owners:
        for tname in M2_TABLES:
            _clean_parquet_dir(out_dir / owner / "data" / tname)

    # Process one M2 table at a time so at most 4 small buffers live in RAM simultaneously.
    for tname in M2_TABLES:
        buffers: dict[str, list[pa.Table]] = {o: [] for o in target_owners}
        buffered_rows: dict[str, int] = {o: 0 for o in target_owners}
        limit = limits[tname]

        for sd in shard_dirs:
            pq_path = sd / f"{tname}.parquet"
            if not pq_path.is_file():
                continue
            table = pq.read_table(pq_path)
            if table.num_rows == 0:
                continue

            unique_ids = table.column("arxiv_id").unique().to_pylist()
            ids_by_owner: dict[str, list[str]] = defaultdict(list)
            for pid in unique_ids:
                owner = range_owner(pid)
                if owner in wanted_set:
                    ids_by_owner[owner].append(pid)

            for owner, pids in ids_by_owner.items():
                mask = pc.is_in(
                    table.column("arxiv_id"), value_set=pa.array(pids, type=pa.string())
                )
                sub = table.filter(mask)
                if sub.num_rows == 0:
                    continue
                buffers[owner].append(sub)
                buffered_rows[owner] += sub.num_rows
                if buffered_rows[owner] >= limit:
                    idx = stats[owner][tname]["shards"]
                    written = _flush_arrow_buffer(
                        tname, buffers[owner], out_dir / owner / "data" / tname, idx
                    )
                    stats[owner][tname]["shards"] += 1
                    stats[owner][tname]["rows"] += written
                    buffers[owner].clear()
                    buffered_rows[owner] = 0

        # Final flush (write an empty schema-valid shard if a range has 0 rows for this table).
        for owner in target_owners:
            if buffers[owner] or stats[owner][tname]["shards"] == 0:
                idx = stats[owner][tname]["shards"]
                written = _flush_arrow_buffer(
                    tname, buffers[owner], out_dir / owner / "data" / tname, idx
                )
                stats[owner][tname]["shards"] += 1
                stats[owner][tname]["rows"] += written
                buffers[owner].clear()
                buffered_rows[owner] = 0

    return stats


def _combined_card(repo_id: str, rows: dict[str, int]) -> str:
    configs = "\n".join(
        f"- config_name: {t}\n  data_files:\n  - split: train\n    path: data/{t}/*.parquet"
        for t in hf_dataset.TABLES
    )
    counts = "\n".join(f"| `{t}` | {rows[t]:,} |" for t in hf_dataset.TABLES)
    return f"""---
license: cc-by-4.0
pretty_name: arXiv Group 1 — Full Assigned Corpus (20,000 Papers)
configs:
{configs}
---

# arXiv Group 1 — Full Corpus Dataset

Milestone 3 output of Group 1 (Intro to Data Science, HCMUS): papers crawled in M1,
parsed in M2, and BibTeX-to-reference matching predictions of M3. Code:
https://github.com/hcmus-arxiv-nhom1/CodeRepo

```python
from datasets import load_dataset
ds = load_dataset("{repo_id}", "predictions", split="train")
```

| Table | Rows |
| --- | ---: |
{counts}
"""


def package_datasets(
    *,
    m1_dir: Path,
    m2_dir: Path,
    out_dir: Path,
    predictions_dir: Path | None = None,
    labels_dir: Path | None = None,
    mode: str = "by-range",
    only_range: str | None = None,
    allow_missing_predictions: bool = False,
    skip_m2: bool = False,
    repo_id_template: str | None = None,
    target_rows: dict[str, int] | None = None,
) -> dict:
    """Assemble M1, M2 and M3 tables into Hugging Face-ready packages under ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if mode == "combined":
        targets = ["all"]
    else:
        targets = [only_range] if only_range else sorted(RANGES)

    m2_stats: dict[str, dict[str, dict[str, int]]] = {}
    if not skip_m2:
        m2_stats = split_m2_tables(
            m2_dir,
            out_dir,
            mode=mode,
            owners=None if mode == "combined" else targets,
            target_rows=target_rows,
        )

    packages_summary: dict[str, dict] = {}
    for target in targets:
        pkg_dir = out_dir / target
        owner_arg = None if target == "all" else target
        table_stats: dict[str, dict[str, int]] = {}

        # Stage M1 tables (papers, references).
        for tname in M1_TABLES:
            sources = _resolve_table_shards(Path(m1_dir), owner_arg, tname)
            if not sources:
                raise FileNotFoundError(f"missing M1 {tname} shards for {target} under {m1_dir}")
            n_shards, n_rows = _copy_shards(sources, pkg_dir / "data" / tname)
            table_stats[tname] = {"shards": n_shards, "rows": n_rows}

        # Record M2 tables (either written just now or pre-existing when --skip-m2 is set).
        for tname in M2_TABLES:
            if target in m2_stats and tname in m2_stats[target]:
                table_stats[tname] = m2_stats[target][tname]
            else:
                existing = sorted((pkg_dir / "data" / tname).glob("*.parquet"))
                if not existing:
                    raise FileNotFoundError(f"missing M2 {tname} shards under {pkg_dir / 'data'}")
                table_stats[tname] = {
                    "shards": len(existing),
                    "rows": sum(pq.ParquetFile(f).metadata.num_rows for f in existing),
                }

        # Stage M3 predictions table (optional if pre-packaging 5/6 tables).
        has_predictions = False
        if predictions_dir is not None:
            pred_sources = _resolve_table_shards(Path(predictions_dir), owner_arg, "predictions")
            if pred_sources:
                n_shards, n_rows = _copy_shards(pred_sources, pkg_dir / "data" / "predictions")
                table_stats["predictions"] = {"shards": n_shards, "rows": n_rows}
                has_predictions = True
        if not has_predictions and not allow_missing_predictions:
            raise FileNotFoundError(
                f"missing predictions shards for {target}; pass --allow-missing-predictions "
                "to pre-package the 5 M1+M2 tables first"
            )

        # Stage label matrices if requested.
        n_labels = 0
        if labels_dir is not None and Path(labels_dir).is_dir():
            if owner_arg is not None:
                n_labels = hf_dataset.stage_labels(Path(labels_dir), owner_arg, pkg_dir)
            else:
                for owner in sorted(RANGES):
                    n_labels += hf_dataset.stage_labels(Path(labels_dir), owner, pkg_dir)

        strict_ok = False
        if has_predictions:
            checked_rows = hf_dataset.check_package(pkg_dir, strict_schema=True)
            strict_ok = True
            if repo_id_template:
                repo_id = repo_id_template.format(owner=target)
                card_text = (
                    _combined_card(repo_id, checked_rows)
                    if owner_arg is None
                    else hf_dataset.card(repo_id, owner_arg, checked_rows, prefix="data/")
                )
                (pkg_dir / "README.md").write_text(card_text, encoding="utf-8")

        pkg_info = {
            "package_dir": str(pkg_dir),
            "tables": table_stats,
            "labels_staged": n_labels,
            "has_predictions": has_predictions,
            "strict_schema_verified": strict_ok,
        }
        (pkg_dir / "package_summary.json").write_text(
            json.dumps(pkg_info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        packages_summary[target] = pkg_info

    overall = {"mode": mode, "packages": packages_summary}
    (out_dir / "package_summary.json").write_text(
        json.dumps(overall, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return overall


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--m1-dir",
        type=Path,
        required=True,
        help="exported M1 Parquet dir (from export_m1_tables.py, combined or split-by-range)",
    )
    p.add_argument(
        "--m2-dir",
        type=Path,
        required=True,
        help="filtered M2 output dir holding shard-*/{elements,hierarchy,bibtex}.parquet",
    )
    p.add_argument("--predictions-dir", type=Path, help="exported predictions Parquet dir")
    p.add_argument("--labels-dir", type=Path, help="optional labels/ folder to stage into package")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--mode", choices=["by-range", "combined"], default="by-range")
    p.add_argument("--range", dest="only_range", choices=sorted(RANGES))
    p.add_argument(
        "--allow-missing-predictions",
        action="store_true",
        help="pre-package the 5 M1+M2 tables before predictions are ready",
    )
    p.add_argument(
        "--skip-m2",
        action="store_true",
        help="reuse already-packaged M2 tables under --out-dir when adding predictions",
    )
    p.add_argument(
        "--repo-id-template",
        help="optional HF repo template (e.g. '<user>/arxiv-nhom1-{owner}') to write README.md",
    )
    a = p.parse_args(argv)
    summary = package_datasets(
        m1_dir=a.m1_dir,
        m2_dir=a.m2_dir,
        out_dir=a.out_dir,
        predictions_dir=a.predictions_dir,
        labels_dir=a.labels_dir,
        mode=a.mode,
        only_range=a.only_range,
        allow_missing_predictions=a.allow_missing_predictions,
        skip_m2=a.skip_m2,
        repo_id_template=a.repo_id_template,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
