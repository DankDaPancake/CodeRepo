# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Write one shard of papers as the three Parquet tables of the M2 statement.

``write_tables(rows, out_dir)`` creates ``elements.parquet``, ``hierarchy.parquet`` and
``bibtex.parquet`` in ``out_dir`` (the runner renames the folder atomically afterwards). The
column types are the ones of the statement; ``kind`` and ``entry_type`` are dictionary-encoded
strings and ``authors`` is a list of strings. An empty table is still written, with its schema,
so every shard has the same three files.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.parser.model import Rows

_DICT = pa.dictionary(pa.int32(), pa.string())

SCHEMAS = {
    "elements": pa.schema(
        [
            pa.field("element_id", pa.string(), nullable=False),
            pa.field("arxiv_id", pa.string(), nullable=False),
            pa.field("kind", _DICT),
            pa.field("content", pa.string()),
        ]
    ),
    "hierarchy": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            pa.field("version", pa.int32()),
            pa.field("element_id", pa.string(), nullable=False),
            pa.field("parent_id", pa.string(), nullable=False),
        ]
    ),
    "bibtex": pa.schema(
        [
            pa.field("arxiv_id", pa.string(), nullable=False),
            pa.field("citation_key", pa.string(), nullable=False),
            pa.field("entry_type", _DICT),
            pa.field("title", pa.string()),
            pa.field("authors", pa.list_(pa.string())),
            pa.field("year", pa.int32()),
            pa.field("doi", pa.string()),
            pa.field("journal", pa.string()),
            pa.field("url", pa.string()),
        ]
    ),
}
COMPRESSION = "zstd"


def to_table(name: str, rows: list[dict]) -> pa.Table:
    """Rows of one table as an Arrow table with the statement's schema."""
    schema = SCHEMAS[name]
    columns = []
    for field in schema:
        values = [row.get(field.name) for row in rows]
        if pa.types.is_dictionary(field.type):
            columns.append(pa.array(values, type=pa.string()).dictionary_encode())
        else:
            columns.append(pa.array(values, type=field.type))
    return pa.Table.from_arrays(columns, schema=schema)


def write_tables(rows: Rows, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in SCHEMAS:
        pq.write_table(
            to_table(name, rows.get(name, [])), out_dir / f"{name}.parquet", compression=COMPRESSION
        )
