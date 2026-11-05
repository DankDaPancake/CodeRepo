# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Stand-ins for the M2 stages of the other members, so that the runner is tested on its own.

They follow the signatures of ``src/parser/model.py``: sentences are the pieces between
dots, equal sentences of one paper share an element ID, an empty version has only its root.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from src.parser.model import Rows, VersionParse, empty_rows


def normalize(text: str) -> str:
    return " ".join(text.split())


def build_tree(text: str) -> list[str]:
    if "BOOM" in text:
        raise ValueError("boom in build_tree")
    if "SLOW" in text:
        time.sleep(30)
    body = text.split("\\begin{document}")[-1].split("\\end{document}")[0]
    body = body.split("\\begin{thebibliography}")[0]  # References are not part of the hierarchy
    return [s.strip() for s in body.split(".") if s.strip()]


def dedup(arxiv_id: str, versions: list[VersionParse]) -> Rows:
    if os.environ.get("M2_FAKE_DEDUP_FAIL") and arxiv_id.endswith("99"):
        raise RuntimeError("dedup failed")
    rows = empty_rows()
    key = arxiv_id.replace(".", "-")
    element_ids: dict[str, str] = {}
    bib_keys: set[str] = set()
    for v in versions:
        root = f"{key}#root{v.version}"
        rows["elements"].append(
            {"element_id": root, "arxiv_id": arxiv_id, "kind": "document", "content": ""}
        )
        rows["hierarchy"].append(
            {"arxiv_id": arxiv_id, "version": v.version, "element_id": root, "parent_id": key}
        )
        for sentence in v.tree or []:
            if sentence not in element_ids:
                element_ids[sentence] = f"{key}#s{len(element_ids) + 1}"
                rows["elements"].append(
                    {
                        "element_id": element_ids[sentence],
                        "arxiv_id": arxiv_id,
                        "kind": "sentence",
                        "content": sentence,
                    }
                )
            rows["hierarchy"].append(
                {
                    "arxiv_id": arxiv_id,
                    "version": v.version,
                    "element_id": element_ids[sentence],
                    "parent_id": root,
                }
            )
        for entry in v.bib:
            if entry.citation_key not in bib_keys:
                bib_keys.add(entry.citation_key)
                rows["bibtex"].append(entry.to_row(arxiv_id))
    return rows


def write_tables(rows: Rows, out_dir: Path) -> None:
    """JSON lines instead of Parquet: the runner only cares that a folder appears atomically."""
    if os.environ.get("M2_FAKE_FAIL_SHARD") == out_dir.name:
        raise OSError(f"disk full while writing {out_dir.name}")
    for table, table_rows in rows.items():
        with open(out_dir / f"{table}.jsonl", "w", encoding="utf-8") as fh:
            for row in table_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
