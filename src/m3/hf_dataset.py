# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Publish one member's range as a public Hugging Face dataset and check it reloads.

    HF_TOKEN=... python -m src.m3.hf_dataset --package-dir pkg/tien \
        --repo-id <hf-user>/arxiv-nhom1-tien --range tien [--labels-dir labels]

``--package-dir`` holds the six tables as sharded Parquet, one folder per table::

    papers/*.parquet  references/*.parquet  elements/*.parquet
    hierarchy/*.parquet  bibtex/*.parquet  predictions/*.parquet

The script checks the folders, writes a dataset card with YAML ``configs`` (one config per
table, no loading script) when ``README.md`` is missing, creates the repo **public** on the
token owner's account, uploads the folder (plus the label matrices of this range under
``labels/``) and then reloads every table with ``datasets`` in streaming mode. The token is
read from ``HF_TOKEN`` (Colab Secret) and is never printed or written to disk.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import pyarrow.parquet as pq

from src.config import RANGES
from src.m3.labels import iter_label_files, range_owner

TABLES = ["papers", "references", "elements", "hierarchy", "bibtex", "predictions"]


def check_package(pkg: Path) -> dict[str, int]:
    """Rows per table; raises if a table is missing or has nested (non-flat) columns."""
    rows = {}
    for t in TABLES:
        files = sorted((pkg / t).glob("*.parquet"))
        if not files:
            raise SystemExit(f"{pkg / t}: no Parquet shard")
        schema = pq.read_schema(files[0])
        nested = [f.name for f in schema if str(f.type).startswith(("struct", "map"))]
        if nested:
            raise SystemExit(f"{t}: nested columns {nested}; columns must be flat")
        rows[t] = sum(pq.ParquetFile(f).metadata.num_rows for f in files)
    return rows


def card(repo_id: str, owner: str, rows: dict[str, int]) -> str:
    start, end = RANGES[owner]
    configs = "\n".join(
        f"- config_name: {t}\n  data_files:\n  - split: train\n    path: {t}/*.parquet"
        for t in TABLES
    )
    counts = "\n".join(f"| `{t}` | {rows[t]:,} |" for t in TABLES)
    return f"""---
license: cc-by-4.0
pretty_name: arXiv group 1 — {start} to {end}
configs:
{configs}
---

# arXiv group 1, range `{start}` – `{end}` ({owner})

Milestone 3 output of group 1 (Intro to Data Science, HCMUS): papers crawled in M1,
parsed in M2, and the BibTeX-to-reference matching of M3. Code:
https://github.com/hcmus-arxiv-nhom1/CodeRepo

```python
from datasets import load_dataset
ds = load_dataset("{repo_id}", "predictions", split="train")
```

| Table | Rows |
| --- | ---: |
{counts}

`labels/manual/*.csv` and `labels/auto/*.csv` are the label matrices: one row per BibTeX
entry (`citation_key`), one column per candidate reference (`ref_arxiv_id`), cells `yes`/`no`,
at most one `yes` per row; a row of only `no` means no candidate is the cited paper.
"""


def stage_labels(labels_dir: Path, owner: str, pkg: Path) -> int:
    n = 0
    for method, pid, path in iter_label_files(labels_dir):
        if range_owner(pid) == owner:
            dest = pkg / "labels" / method / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            n += 1
    return n


def verify(repo_id: str, rows: dict[str, int]) -> None:
    from datasets import load_dataset

    for t in TABLES:
        it = load_dataset(repo_id, t, split="train", streaming=True)
        first = next(iter(it), None)
        if rows[t] and first is None:
            raise SystemExit(f"{t}: reload returned no row")
        print(f"reload ok  {t:<12} columns={list(first or {})}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--package-dir", type=Path, required=True)
    p.add_argument("--repo-id", required=True, help="<hf-user>/<dataset-name>")
    p.add_argument("--range", required=True, choices=sorted(RANGES))
    p.add_argument("--labels-dir", type=Path, help="copy this range's label matrices into labels/")
    p.add_argument("--dry-run", action="store_true", help="check and write the card, no upload")
    a = p.parse_args(argv)

    rows = check_package(a.package_dir)
    for t in TABLES:
        print(f"{t:<12} {rows[t]:>12,} rows")
    if a.labels_dir:
        print(f"labels: {stage_labels(a.labels_dir, a.range, a.package_dir)} files")
    readme = a.package_dir / "README.md"
    if not readme.exists():
        readme.write_text(card(a.repo_id, a.range, rows), encoding="utf-8")
        print(f"wrote {readme}")
    if a.dry_run:
        return

    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("HF_TOKEN missing; set it as a Colab Secret, never in code")
    api = HfApi(token=token)
    api.create_repo(a.repo_id, repo_type="dataset", private=False, exist_ok=True)
    api.update_repo_settings(
        a.repo_id, repo_type="dataset", private=False
    )  # existing repo: force public
    api.upload_folder(
        repo_id=a.repo_id,
        repo_type="dataset",
        folder_path=str(a.package_dir),
        allow_patterns=["README.md", *(f"{t}/*.parquet" for t in TABLES), "labels/**"],
        commit_message="M3: six tables, labels and dataset card",
    )
    print(f"uploaded https://huggingface.co/datasets/{a.repo_id}")
    verify(a.repo_id, rows)


if __name__ == "__main__":
    main()
