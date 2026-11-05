# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Run the whole M2 parser over a corpus with one command; stop it and run it again.

    python -m src.parser.run --data-root data/corpus --out-dir data/m2 --work-dir work/m2
    python -m src.parser.run --data-root data/corpus --out-dir data/m2 --limit 20
    python -m src.parser.run --data-root data/corpus --workers 2 --shard-papers 100
    python -m src.parser.run --data-root data/corpus --scan          # gather + references only

Per paper (papers are independent, deduplication is per publication) and per version:
``gather`` -> ``expand`` -> ``normalize`` -> ``build_tree`` and ``extract_references``; then
``dedup`` over all versions of the paper. The stages are plain functions named in ``STAGES``
(``module:function``, see ``src/parser/model.py`` for the signatures); ``--stage
build_tree=pkg.mod:fn`` swaps one. Nothing is written until every stage can be imported.

Versions without TeX (statement: "record it as empty, do not skip it"):
- ``empty``    the ``vN/`` folder has no ``.tex`` (PDF-only, 404 or empty record of M1);
- ``no_root``  ``.tex`` files but no ``\\documentclass``;
- ``missing``  no ``vN/`` folder although ``metadata.json`` says the version exists (crawl
  failed or not finished): reported, not passed to ``dedup``;
- ``error``    a stage raised; the other versions of the paper are still parsed.
Each is handed to ``dedup`` as a ``VersionParse`` without tree (except ``missing``), so the tables
can list the version; the journal keeps the status for the coverage statistics.

Resume. Papers are processed in folder order and written in *shards* of ``--shard-papers``
papers (or ``--shard-rows`` rows, whichever comes first). A shard is written to
``<out-dir>/.staging/``, renamed to ``<out-dir>/shard-NNNNN/`` and only then appended to
``<work-dir>/shards.jsonl`` (flushed and fsynced): that line is the commit. After a kill,
the same command skips every committed paper, deletes the half-written shard and goes on, so
at most one shard is lost. To parse a *changed* corpus (the crawl went on), use a new
``--out-dir``: committed rows are never rewritten (``--verify-done`` stops with an error if
a committed paper changed on disk, ``--retry-errors`` re-runs papers that failed and have no rows).

Outputs:
    <out-dir>/shard-NNNNN/…       whatever ``write_tables`` writes (Parquet: Hiếu)
    <work-dir>/shards.jsonl       commit journal, one line per shard with a record per paper
    <work-dir>/m2_versions.csv    one row per version: status, root, files, references (for stats)
    <work-dir>/m2_papers.csv      one row per paper: outcome and rows written
    <work-dir>/run_summary.json   counts and timings of the last run (runs.jsonl keeps all)
    <work-dir>/run.log, run.lock

``--workers N`` runs N processes over the papers (results are written in folder order by the
parent, so shards do not depend on N). ``--paper-timeout`` (POSIX only) turns a paper that
runs too long into an ``error`` instead of stalling the run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import itertools
import json
import logging
import os
import shutil
import signal
import sys
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tqdm import tqdm

from src import config
from src.crawler.worklock import WorkDirLock, WorkDirLockedError
from src.parser.bibitem import extract_references
from src.parser.gather import TexVersion
from src.parser.model import (
    EMPTY,
    ERROR,
    MISSING,
    NO_ROOT,
    PARSED,
    Rows,
    VersionParse,
    count_rows,
    empty_rows,
    extend_rows,
)
from src.utils.ids import from_folder_name, to_folder_name

log = logging.getLogger("src.parser.run")

STAGES = {
    "normalize": "src.parser.normalize:normalize",
    "build_tree": "src.parser.hierarchy:build_tree",
    "dedup": "src.parser.dedup:dedup",
    "write_tables": "src.parser.writer:write_tables",
}
SHARD_DIR = "shard-{:05d}"
STAGING = ".staging"
RECYCLE_AFTER = 500  # papers per worker process before it is replaced (bounds memory growth)
VERSION_COLUMNS = (
    "arxiv_id version status reason crawl_status root n_files n_unused n_other_roots "
    "n_missing_includes n_bibitems n_bib_cited n_bib_unused missing_bib secs"
).split()
PAPER_COLUMNS = (
    "arxiv_id shard n_versions n_parsed n_empty n_no_root n_missing n_error error "
    "elements hierarchy bibtex elapsed_s"
).split()


class StageError(RuntimeError):
    """A stage cannot be imported."""


class ChangedCorpusError(RuntimeError):
    """A paper committed earlier no longer matches the corpus on disk."""


class PaperTimeout(BaseException):  # not an Exception: no stage may swallow it
    pass


@dataclass(frozen=True)
class Options:
    """Everything a worker process needs; plain data so that it can be pickled."""

    stages: dict[str, str] = field(default_factory=lambda: dict(STAGES))
    scan: bool = False  # gather + references only: no tree, no tables
    paper_timeout_s: float = 0.0  # 0 = none


@dataclass
class PaperOutcome:
    arxiv_id: str
    folder: str
    fingerprint: str
    versions: list[dict]
    rows: Rows
    error: str | None
    elapsed_s: float


# --------------------------------------------------------------------------- stages

_loaded: dict[str, Callable] = {}


def load_stage(spec: str) -> Callable:
    """``"package.module:function"`` -> the function (cached per process)."""
    if spec not in _loaded:
        module, _, attr = spec.partition(":")
        try:
            _loaded[spec] = getattr(importlib.import_module(module), attr)
        except (ImportError, AttributeError) as exc:
            raise StageError(f"{spec}: {exc}") from exc
    return _loaded[spec]


def check_stages(options: Options) -> list[str]:
    """Problems that would stop the run, found before anything is processed."""
    if options.scan:
        return []
    problems = []
    for name, spec in options.stages.items():
        try:
            load_stage(spec)
        except StageError as exc:
            problems.append(f"stage {name!r}: {exc}")
    return problems


def _normalize(options: Options, text: str) -> str:
    return text if options.scan else load_stage(options.stages["normalize"])(text)


def _build_tree(options: Options, text: str):
    return None if options.scan else load_stage(options.stages["build_tree"])(text)


def _dedup(options: Options, arxiv_id: str, versions: list[VersionParse]) -> Rows:
    return empty_rows() if options.scan else load_stage(options.stages["dedup"])(arxiv_id, versions)


# --------------------------------------------------------------------------- one paper


@contextmanager
def time_limit(seconds: float):
    """Raise ``PaperTimeout`` after ``seconds`` (POSIX main thread only; otherwise a no-op)."""
    usable = (
        seconds
        and hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    )
    if not usable:
        yield
        return

    def expired(signum, frame):
        raise PaperTimeout(f"timeout after {seconds:g} s")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def fingerprint(paper_dir: Path) -> str:
    """Hash of the relative path and size of every file of a paper (cheap, no content read)."""
    digest = hashlib.sha1()
    for path in sorted(p for p in paper_dir.rglob("*") if p.is_file()):
        digest.update(f"{path.relative_to(paper_dir).as_posix()}\0{path.stat().st_size}\n".encode())
    return digest.hexdigest()[:16]


def _read_metadata(paper_dir: Path) -> dict:
    return json.loads((paper_dir / "metadata.json").read_text(encoding="utf-8"))


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _parse_version(
    vdir: Path, title: str | None, version: int, options: Options, crawl: dict | None
) -> tuple[dict, VersionParse | None]:
    """One version -> its journal record and what ``dedup`` gets (None for a missing folder)."""
    info = dict.fromkeys(VERSION_COLUMNS, None)
    info.update(version=version, crawl_status=(crawl or {}).get("status"))
    if not vdir.is_dir():
        info.update(status=MISSING, reason="no version folder")
        return info, None
    started = time.perf_counter()
    try:
        tex = TexVersion(vdir, title)
        if not tex.tex:
            reason = info["crawl_status"] or "no .tex file"
            info.update(status=EMPTY, reason=reason)
            return info, VersionParse(version, EMPTY)
        found = tex.gather()
        info.update(
            n_files=len(found.files),
            n_unused=len(found.unused),
            n_other_roots=len(found.other_roots),
            n_missing_includes=len(found.missing),
        )
        if found.root is None:
            info.update(status=NO_ROOT, reason="no \\documentclass")
            return info, VersionParse(version, NO_ROOT)
        refs = extract_references(tex, found.files)
        tree = _build_tree(options, _normalize(options, tex.expand(found.root)))
        info.update(
            status=PARSED,
            root=found.root,
            n_bibitems=refs.n_bibitems,
            n_bib_cited=refs.n_bib_cited,
            n_bib_unused=refs.n_bib_unused,
            missing_bib=";".join(refs.missing_bib) or None,
        )
        return info, VersionParse(version, PARSED, tree, refs.entries)
    except Exception as exc:  # one bad version must not cost the paper or the run
        info.update(status=ERROR, reason=_short(exc))
        return info, VersionParse(version, ERROR)
    finally:
        info["secs"] = round(time.perf_counter() - started, 4)


def process_paper(
    paper_dir: Path, options: Options, crawl: dict[int, dict] | None = None
) -> PaperOutcome:
    """Parse every version of one paper and deduplicate them. Never raises (except Ctrl+C)."""
    started = time.perf_counter()
    paper_dir = Path(paper_dir)
    folder, error = paper_dir.name, None
    versions: list[dict] = []
    rows = empty_rows()
    arxiv_id = from_folder_name(folder) if _is_folder_name(folder) else folder
    try:
        with time_limit(options.paper_timeout_s):
            meta = _read_metadata(paper_dir)
            arxiv_id = meta.get("arxiv_id") or arxiv_id
            n_versions = int(meta.get("num_versions") or 0) or _count_version_dirs(paper_dir)
            parses = []
            for number in range(1, n_versions + 1):
                info, parse = _parse_version(
                    paper_dir / f"v{number}",
                    meta.get("title"),
                    number,
                    options,
                    (crawl or {}).get(number),
                )
                versions.append(info)
                if parse is not None:
                    parses.append(parse)
            if parses:
                rows = _dedup(options, arxiv_id, parses)
    except (Exception, PaperTimeout) as exc:
        error, rows = _short(exc), empty_rows()
    return PaperOutcome(
        arxiv_id=arxiv_id,
        folder=folder,
        fingerprint=fingerprint(paper_dir),
        versions=versions,
        rows=rows,
        error=error,
        elapsed_s=round(time.perf_counter() - started, 4),
    )


def _is_folder_name(name: str) -> bool:
    try:
        from_folder_name(name)
    except ValueError:
        return False
    return True


def _count_version_dirs(paper_dir: Path) -> int:
    numbers = [int(p.name[1:]) for p in paper_dir.iterdir() if p.is_dir() and p.name[1:].isdigit()]
    return max(numbers, default=0)


# --------------------------------------------------------------------------- journal


class Journal:
    """``shards.jsonl``: one line per committed shard, appended last, flushed and fsynced."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[dict[str, dict], list[int]]:
        """(latest record per paper, committed shard numbers); a torn last line is dropped."""
        papers: dict[str, dict] = {}
        shards: list[int] = []
        if not self.path.exists():
            return papers, shards
        data = self.path.read_bytes()
        if data and not data.endswith(b"\n"):  # killed in the middle of a write
            data = data[: data.rfind(b"\n") + 1]
            self.path.write_bytes(data)
        for line in data.decode("utf-8").splitlines():
            try:
                shard = json.loads(line)
            except json.JSONDecodeError:
                continue
            shards.append(shard["shard"])
            for record in shard["papers"]:
                papers[record["arxiv_id"]] = {**record, "shard": shard["shard"]}
        return papers, shards

    def append(self, record: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def clean_orphans(out_dir: Path, committed: list[int]) -> list[str]:
    """Delete the staging area and shard folders the journal does not know (a killed run)."""
    removed = []
    if (out_dir / STAGING).exists():
        shutil.rmtree(out_dir / STAGING)
        removed.append(STAGING)
    known = {SHARD_DIR.format(n) for n in committed}
    for path in sorted(out_dir.glob("shard-*")):
        if path.is_dir() and path.name not in known:
            shutil.rmtree(path)
            removed.append(path.name)
    return removed


# --------------------------------------------------------------------------- corpus


def list_papers(data_root: Path) -> list[Path]:
    return sorted(
        p for p in Path(data_root).iterdir() if p.is_dir() and (p / "metadata.json").is_file()
    )


def select_papers(
    papers: list[Path], ids: list[str] | None, offset: int, limit: int | None
) -> list[Path]:
    if ids:
        wanted = {to_folder_name(i) for i in ids}
        papers = [p for p in papers if p.name in wanted]
    papers = papers[offset:]
    return papers[:limit] if limit is not None else papers


def crawl_index(work_dir: Path | None) -> dict[str, dict[int, dict]]:
    """arxiv_id -> {version: crawler record} from the crawler's ``versions.jsonl``."""
    index: dict[str, dict[int, dict]] = {}
    if work_dir is None:
        return index
    from src.run_pipeline import load_version_state

    for (arxiv_id, version), rec in load_version_state(Path(work_dir) / "versions.jsonl").items():
        index.setdefault(arxiv_id, {})[version] = {
            "status": rec.get("status"),
            "kind": rec.get("kind"),
        }
    return index


# --------------------------------------------------------------------------- run


def _outcomes(
    papers: list[Path], options: Options, crawl: dict[str, dict[int, dict]], workers: int
) -> Iterator[PaperOutcome]:
    """Outcomes in the order of ``papers``, whatever the number of workers."""

    def crawl_of(path: Path) -> dict[int, dict] | None:
        return crawl.get(from_folder_name(path.name)) if _is_folder_name(path.name) else None

    if workers <= 1:
        for path in papers:
            yield process_paper(path, options, crawl_of(path))
        return
    with ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=RECYCLE_AFTER) as pool:
        remaining = iter(papers)
        window = deque(
            pool.submit(process_paper, p, options, crawl_of(p))
            for p in itertools.islice(remaining, workers * 2)
        )
        while window:
            outcome = window.popleft().result()
            if (nxt := next(remaining, None)) is not None:
                window.append(pool.submit(process_paper, nxt, options, crawl_of(nxt)))
            yield outcome


def _record(outcome: PaperOutcome) -> dict:
    return {
        "arxiv_id": outcome.arxiv_id,
        "folder": outcome.folder,
        "fingerprint": outcome.fingerprint,
        "error": outcome.error,
        "elapsed_s": outcome.elapsed_s,
        "rows": count_rows(outcome.rows),
        "versions": outcome.versions,
    }


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def export_csv(work_dir: Path, papers: dict[str, dict]) -> None:
    """Rebuild ``m2_versions.csv`` and ``m2_papers.csv`` from the journal (always consistent)."""
    version_rows, paper_rows = [], []
    for arxiv_id in sorted(papers):
        rec = papers[arxiv_id]
        counts = Counter(v["status"] for v in rec["versions"])
        paper_rows.append(
            {
                "arxiv_id": arxiv_id,
                "shard": rec["shard"],
                "n_versions": len(rec["versions"]),
                "n_parsed": counts[PARSED],
                "n_empty": counts[EMPTY],
                "n_no_root": counts[NO_ROOT],
                "n_missing": counts[MISSING],
                "n_error": counts[ERROR],
                "error": rec["error"],
                "elapsed_s": rec["elapsed_s"],
                **rec["rows"],
            }
        )
        version_rows.extend({**v, "arxiv_id": arxiv_id} for v in rec["versions"])
    _atomic_csv(work_dir / "m2_versions.csv", VERSION_COLUMNS, version_rows)
    _atomic_csv(work_dir / "m2_papers.csv", PAPER_COLUMNS, paper_rows)


def run(
    data_root: Path,
    out_dir: Path,
    work_dir: Path,
    *,
    options: Options | None = None,
    ids: list[str] | None = None,
    offset: int = 0,
    limit: int | None = None,
    workers: int = 1,
    shard_papers: int = 100,
    shard_rows: int = 200_000,
    retry_errors: bool = False,
    verify_done: bool = False,
    crawl_work_dir: Path | None = None,
    progress: bool = True,
) -> dict:
    """Parse the selected papers not committed yet; returns the summary (also written)."""
    options = options or Options()
    if problems := check_stages(options):
        raise StageError("; ".join(problems))
    data_root, out_dir, work_dir = Path(data_root), Path(out_dir), Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    lock = WorkDirLock(work_dir)
    lock.acquire()  # raises WorkDirLockedError: two runs must not share a journal
    started_at, t0 = _now(), time.perf_counter()
    interrupted = True
    journal = Journal(work_dir / "shards.jsonl")
    done, committed = journal.load()
    this_run: list[PaperOutcome] = []
    written = Counter()
    try:
        if not options.scan:
            out_dir.mkdir(parents=True, exist_ok=True)
            if removed := clean_orphans(out_dir, committed):
                log.warning("removed unfinished output of an earlier run: %s", removed)
        selected = select_papers(list_papers(data_root), ids, offset, limit)
        if verify_done:
            changed = [
                p.name
                for p in selected
                if (rec := done.get(_id_of(p))) and rec["fingerprint"] != fingerprint(p)
            ]
            if changed:
                raise ChangedCorpusError(
                    f"{len(changed)} committed paper(s) changed on disk (first: {changed[:5]}); "
                    "parse into a new --out-dir"
                )
        pending = [
            p
            for p in selected
            if (rec := done.get(_id_of(p))) is None or (retry_errors and rec["error"])
        ]
        log.info(
            "%d papers selected, %d committed, %d to parse",
            len(selected),
            len(selected) - len(pending),
            len(pending),
        )

        buffer: list[PaperOutcome] = []
        buffered_rows = 0
        next_shard = max(committed, default=-1) + 1

        def commit() -> None:
            nonlocal buffer, buffered_rows, next_shard
            if not buffer:
                return
            rows = empty_rows()
            for item in buffer:
                extend_rows(rows, item.rows)
            if not options.scan:
                staging = out_dir / STAGING / SHARD_DIR.format(next_shard)
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(parents=True)
                load_stage(options.stages["write_tables"])(rows, staging)
                os.replace(staging, out_dir / SHARD_DIR.format(next_shard))
                with suppress(OSError):  # only if nothing else is staged
                    staging.parent.rmdir()
            records = [_record(item) for item in buffer]
            journal.append({"shard": next_shard, "committed_at": _now(), "papers": records})
            for record in records:
                done[record["arxiv_id"]] = {**record, "shard": next_shard}
            written.update(count_rows(rows))
            written["shards"] += 1
            committed.append(next_shard)
            next_shard += 1
            buffer, buffered_rows = [], 0

        bar = tqdm(total=len(pending), unit="paper", disable=not progress, dynamic_ncols=True)
        try:
            for outcome in _outcomes(pending, options, crawl_index(crawl_work_dir), workers):
                this_run.append(outcome)
                buffer.append(outcome)
                buffered_rows += sum(count_rows(outcome.rows).values())
                if outcome.error:
                    log.warning("%s failed: %s", outcome.arxiv_id, outcome.error)
                bar.update(1)
                if len(buffer) >= shard_papers or buffered_rows >= shard_rows:
                    commit()
        finally:
            bar.close()
            commit()  # a Ctrl+C or an error keeps the papers already parsed
        interrupted = False
    finally:
        if committed or done:
            export_csv(work_dir, done)
        summary = _summary(
            started_at,
            time.perf_counter() - t0,
            interrupted,
            this_run,
            done,
            written,
            workers,
            options,
        )
        (work_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        with open(work_dir / "runs.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary) + "\n")
        lock.release()
    return summary


def _id_of(path: Path) -> str:
    """The arXiv ID a folder is journaled under (``metadata.json`` first, else the name)."""
    try:
        return _read_metadata(path).get("arxiv_id") or from_folder_name(path.name)
    except (OSError, ValueError, json.JSONDecodeError):
        return path.name


def _summary(started_at, wall_s, interrupted, outcomes, done, written, workers, options) -> dict:
    versions = Counter(v["status"] for o in outcomes for v in o.versions)
    return {
        "started_at": started_at,
        "finished_at": _now(),
        "interrupted": interrupted,
        "scan_only": options.scan,
        "workers": workers,
        "wall_s": round(wall_s, 3),
        "papers_this_run": len(outcomes),
        "papers_failed_this_run": sum(o.error is not None for o in outcomes),
        "avg_paper_s": round(wall_s / len(outcomes), 4) if outcomes else None,
        "papers_committed_total": len(done),
        "version_status_this_run": dict(versions),
        "rows_written_this_run": {k: written[k] for k in ("elements", "hierarchy", "bibtex")},
        "shards_written_this_run": written["shards"],
    }


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=Path(config.DEFAULT_DATA_ROOT))
    parser.add_argument("--out-dir", type=Path, default=Path("data/m2"))
    parser.add_argument("--work-dir", type=Path, default=Path("work/m2"))
    parser.add_argument("--crawl-work-dir", type=Path, help="crawler work/ with versions.jsonl")
    parser.add_argument("--ids", help="comma-separated arXiv IDs, or @file with one per line")
    parser.add_argument("--offset", type=int, default=0, help="skip the first N papers")
    parser.add_argument("--limit", type=int, help="parse at most N papers")
    parser.add_argument("--workers", type=int, default=1, help="processes (default 1)")
    parser.add_argument("--shard-papers", type=int, default=100)
    parser.add_argument("--shard-rows", type=int, default=200_000)
    parser.add_argument(
        "--paper-timeout", type=float, default=0.0, help="seconds per paper (POSIX)"
    )
    parser.add_argument("--retry-errors", action="store_true", help="re-run papers that failed")
    parser.add_argument(
        "--verify-done", action="store_true", help="fail if a committed paper changed"
    )
    parser.add_argument("--scan", action="store_true", help="gather + references only, no tables")
    parser.add_argument(
        "--stage",
        action="append",
        default=[],
        metavar="NAME=MODULE:FUNCTION",
        help="replace a stage",
    )
    parser.add_argument("--no-progress", action="store_true")
    return parser


def _read_ids(value: str | None) -> list[str] | None:
    if not value:
        return None
    raw = (
        Path(value[1:]).read_text(encoding="utf-8").split()
        if value.startswith("@")
        else value.split(",")
    )
    return [i.strip() for i in raw if i.strip()]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stages = dict(STAGES)
    for item in args.stage:
        name, _, spec = item.partition("=")
        if name not in STAGES or ":" not in spec:
            raise SystemExit(f"--stage expects NAME=MODULE:FUNCTION with NAME in {sorted(STAGES)}")
        stages[name] = spec
    options = Options(stages=stages, scan=args.scan, paper_timeout_s=args.paper_timeout)

    args.work_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(args.work_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)
    logging.getLogger().setLevel(logging.INFO)
    try:
        summary = run(
            args.data_root,
            args.out_dir,
            args.work_dir,
            options=options,
            ids=_read_ids(args.ids),
            offset=args.offset,
            limit=args.limit,
            workers=args.workers,
            shard_papers=args.shard_papers,
            shard_rows=args.shard_rows,
            retry_errors=args.retry_errors,
            verify_done=args.verify_done,
            crawl_work_dir=args.crawl_work_dir,
            progress=not args.no_progress,
        )
    except StageError as exc:
        print(
            f"not started, a stage is missing: {exc}\n(use --scan to run without the stages)",
            file=sys.stderr,
        )
        return 3
    except WorkDirLockedError as exc:
        print(f"not started: {exc}", file=sys.stderr)
        return 2
    except ChangedCorpusError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("interrupted: run the same command to resume", file=sys.stderr)
        return 130
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
