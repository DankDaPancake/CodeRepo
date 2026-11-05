# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Types shared by the M2 stages, so that no stage has to import another one.

The runner (``src/parser/run.py``) calls, per paper and in this order:

    normalize(text: str) -> str                              # Tiến: cleanup + math normalisation
    build_tree(text: str) -> object                          # Đăng: the hierarchy of one version
    dedup(arxiv_id: str, versions: list[VersionParse]) -> Rows   # Tiến: one paper, all versions
    write_tables(rows: Rows, out_dir: Path) -> None          # Hiếu: one shard of papers

``Rows`` is the plain dict below, so a stage needs nothing from the runner to produce it.
``tree`` is opaque to the runner: ``build_tree`` and ``dedup`` agree on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.parser.bibitem import BibEntry

TABLES = ("elements", "hierarchy", "bibtex")  # the three M2 output tables

Rows = dict[str, list[dict]]  # table name -> rows, keys are TABLES

# Outcome of one version. Only "parsed" carries a tree; every other status is recorded in the
# journal and handed to ``dedup`` as an empty version (statement: "record it as empty").
PARSED = "parsed"
EMPTY = "empty"  # the vN/ folder has no .tex file (PDF-only, 404, empty record of M1)
NO_ROOT = "no_root"  # .tex files, but none with \documentclass
ERROR = "error"  # a stage raised on this version
MISSING = "missing"  # no vN/ folder at all (crawl failed or unfinished): not passed to ``dedup``


@dataclass
class VersionParse:
    """What ``dedup`` gets for one version of a paper."""

    version: int
    status: str  # PARSED, EMPTY, NO_ROOT or ERROR
    tree: Any = None  # ``build_tree`` result when parsed, else None
    bib: list[BibEntry] = field(default_factory=list)  # the version's references


def empty_rows() -> Rows:
    return {table: [] for table in TABLES}


def count_rows(rows: Rows) -> dict[str, int]:
    return {table: len(rows.get(table, ())) for table in TABLES}


def extend_rows(target: Rows, other: Rows) -> None:
    for table in TABLES:
        target[table].extend(other.get(table, ()))
