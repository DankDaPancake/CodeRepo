# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""M3 label format and the shared loaders used by every M3 tool.

Label format (one CSV per paper, ``<labels-dir>/<method>/<folder>.csv``, ``method`` is
``manual`` or ``auto``) is the candidate matrix of the statement:

    citation_key,2602.17657,2401.00001,...      <- header: one column per candidate ref_arxiv_id
    smith2020,no,yes,...                          <- one row per BibTeX entry, cells yes/no

Each row has exactly one ``yes`` (the matching reference) or only ``no`` (no matching
reference among the candidates). Candidates of a paper are the rows of the ``references``
table for that paper: the references of ``references.json`` with a non-null ``arxiv_id``
(data contract, section 6), deduplicated by arXiv ID in their original order.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pyarrow.dataset as ds

from src.config import RANGES
from src.utils.ids import from_folder_name, to_folder_name

BIBTEX_COLUMNS = ["arxiv_id", "citation_key", "title", "authors", "year", "doi", "journal", "url"]
METHODS = ("manual", "auto")


# ---------------------------------------------------------------- loaders


def load_bibtex(m2_dir: Path, arxiv_ids=None, columns=BIBTEX_COLUMNS) -> list[dict]:
    """BibTeX rows of the M2 shards (``<m2_dir>/shard-*/bibtex.parquet``).

    Only the requested papers and columns are read, so the full table never sits in RAM.
    """
    files = sorted(Path(m2_dir).glob("shard-*/bibtex.parquet"))
    if not files:
        raise FileNotFoundError(f"no shard-*/bibtex.parquet under {m2_dir}")
    dataset = ds.dataset([str(f) for f in files], format="parquet")
    flt = None if arxiv_ids is None else ds.field("arxiv_id").isin(sorted(set(arxiv_ids)))
    return dataset.to_table(columns=columns, filter=flt).to_pylist()


def load_candidates(corpus_dir: Path, arxiv_id: str) -> list[dict]:
    """Rows of the ``references`` table of one paper (candidates), empty if no file."""
    path = Path(corpus_dir) / to_folder_name(arxiv_id) / "references.json"
    if not path.exists():
        return []
    refs = json.loads(path.read_text(encoding="utf-8")).get("references") or []
    seen, out = set(), []
    for ref in refs:
        ref_id = ref.get("arxiv_id")
        if not ref_id or ref_id in seen:
            continue
        seen.add(ref_id)
        out.append(
            {
                "ref_arxiv_id": ref_id,
                "ref_title": ref.get("title"),
                "ref_authors": ref.get("authors") or [],
                "ref_submission_date": ref.get("submission_date"),
            }
        )
    return out


def range_owner(arxiv_id: str) -> str | None:
    """Owner of the ID range containing ``arxiv_id`` (``config.RANGES``), else None."""
    for owner, (start, end) in RANGES.items():
        # all range IDs are new-style with the same width, so string order is numeric order
        if len(arxiv_id) == len(start) and start <= arxiv_id <= end:
            return owner
    return None


# ---------------------------------------------------------------- similarity (display + analysis)


def norm_text(text) -> str:
    """Lower case, accents and LaTeX braces/commands removed, punctuation -> spaces."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text).lower()
    return " ".join(text.split())


def title_sim(a, b) -> float:
    a, b = norm_text(a), norm_text(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def last_names(authors) -> set[str]:
    """Normalized last names; handles ``Last, First`` and ``First Last``."""
    out = set()
    for name in authors or []:
        name = str(name)
        last = name.split(",")[0] if "," in name else (name.split() or [""])[-1]
        last = norm_text(last)
        if last and last not in {"others", "al"}:
            out.add(last)
    return out


def author_overlap(a, b) -> float:
    """Jaccard overlap of last names (0 when either side has none)."""
    a, b = last_names(a), last_names(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def ref_year(candidate: dict) -> int | None:
    date = candidate.get("ref_submission_date")
    return int(str(date)[:4]) if date and str(date)[:4].isdigit() else None


# ---------------------------------------------------------------- label files


def label_path(labels_dir: Path, method: str, arxiv_id: str) -> Path:
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")
    return Path(labels_dir) / method / f"{to_folder_name(arxiv_id)}.csv"


def write_matrix(path: Path, candidate_ids: list[str], answers: dict[str, str | None]) -> None:
    """Write the yes/no matrix. ``answers`` maps citation_key -> ref_arxiv_id or None."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["citation_key", *candidate_ids])
        for key, ref in answers.items():
            if ref is not None and ref not in candidate_ids:
                raise ValueError(f"{key}: {ref} is not a candidate")
            w.writerow([key, *("yes" if c == ref else "no" for c in candidate_ids)])
    tmp.replace(path)  # atomic: a crash never leaves a half-written label file


def read_matrix(path: Path) -> tuple[list[str], dict[str, str | None]]:
    """(candidate ids, citation_key -> ref_arxiv_id or None); raises on an invalid matrix."""
    with Path(path).open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0][:1] != ["citation_key"]:
        raise ValueError(f"{path}: header must start with citation_key")
    candidates = rows[0][1:]
    if len(set(candidates)) != len(candidates):
        raise ValueError(f"{path}: duplicate candidate columns")
    answers: dict[str, str | None] = {}
    for i, row in enumerate(rows[1:], start=2):
        key, cells = row[0], row[1:]
        if len(cells) != len(candidates):
            raise ValueError(f"{path}:{i}: {len(cells)} cells for {len(candidates)} candidates")
        if any(c not in ("yes", "no") for c in cells):
            raise ValueError(f"{path}:{i}: cells must be yes/no")
        yes = [c for c, v in zip(candidates, cells, strict=True) if v == "yes"]
        if len(yes) > 1:
            raise ValueError(f"{path}:{i}: {key} has {len(yes)} yes cells, at most one allowed")
        if key in answers:
            raise ValueError(f"{path}:{i}: duplicate citation_key {key}")
        answers[key] = yes[0] if yes else None
    return candidates, answers


def iter_label_files(labels_dir: Path, method: str | None = None):
    """Yield (method, arxiv_id, path) for every label file."""
    for m in [method] if method else METHODS:
        for path in sorted((Path(labels_dir) / m).glob("*.csv")):
            yield m, from_folder_name(path.stem), path
