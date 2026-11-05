<!-- Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules. -->
# Spec 0005 — M2 runner, stage interfaces and reference extraction

- **Author:** Thiên (Member 1) · **Reviewers:** Đăng (owner of the M2 table schema), Tiến, Hiếu · **Status:** awaiting review
- **Date:** 01/11/2026 · **Branch:** `feat/m2-runner`

## Context

The M2 action plan (01/11) gives Thiên the shared runner ("one command for the whole corpus: versions without TeX recorded as empty, stop and resume"), `\bibitem` → BibTeX and the error hunt in `gather`. The runner is the glue of everybody's stages, so it fixes their call signatures here, in one place, for Gate 1 ("stable interfaces"). It does **not** change the three output tables (`elements`, `hierarchy`, `bibtex`) of the M2 schema: it only adds files under `work/`, which [`docs/data_contract.md`](../docs/data_contract.md) §1 lists.

## Stage interfaces (proposal, one line each to change)

Per paper, in order; `Rows` is `{"elements": [...], "hierarchy": [...], "bibtex": [...]}` of plain dicts, `VersionParse` is in `src/parser/model.py`.

| Stage | Module : function | Signature | Owner |
| --- | --- | --- | --- |
| cleanup + math | `src.parser.normalize:normalize` | `(text: str) -> str` | Tiến |
| hierarchy of one version | `src.parser.hierarchy:build_tree` | `(text: str) -> tree` (opaque to the runner) | Đăng |
| deduplication, IDs, rows of one paper | `src.parser.dedup:dedup` | `(arxiv_id: str, versions: list[VersionParse]) -> Rows` | Tiến |
| write a shard | `src.parser.writer:write_tables` | `(rows: Rows, out_dir: Path) -> None`, creates its files in `out_dir` | Hiếu |

`gather`, `expand` and `extract_references` (Thiên) run before `normalize`. `dedup` receives **every** version that has a folder, in order; a version without TeX arrives as `VersionParse(version, "empty" | "no_root" | "error")` with `tree=None`, so the writer can emit its root row (`#rootN`) and the version shows up in `hierarchy`. A `missing` version (no `vN/` folder) is not passed on.

**Open question for the M2 schema spec:** what an empty version looks like in `hierarchy`. The runner assumes one `document` root per version, with nothing below it.

## Resume protocol

1. A shard is written to `<out>/.staging/shard-N/` by `write_tables`, renamed to `<out>/shard-N/` (a directory rename is atomic, so three Parquet files appear together), then one line is appended to `<work>/shards.jsonl` and fsynced. **That line is the commit.**
2. On start: a torn last line is dropped, `.staging/` and every `shard-*` folder without a journal line are deleted, committed papers are skipped. At most one shard of work is lost.
3. Rows of a committed paper are never rewritten. A corpus that changed (crawl went on) is parsed into a new `--out-dir`; `--verify-done` fails fast when a committed paper changed (path + size fingerprint). `--retry-errors` re-runs papers that failed and so have no rows.
4. Shards close after `--shard-papers` papers or `--shard-rows` rows (bounded RAM); results are consumed in folder order, so `--workers N` does not change the shards.

## Statistics files

`work/m2_versions.csv` (one row per version: `status`, `reason`, `crawl_status`, `root`, `n_files`, `n_unused`, `n_other_roots`, `n_missing_includes`, `n_bibitems`, `n_bib_cited`, `n_bib_unused`, `missing_bib`, `secs`) and `work/m2_papers.csv` (one row per paper: version counts per status, `error`, rows written, `elapsed_s`) are rebuilt from the journal at the end of every run. They answer *parsing success rate* and *version coverage per publication* of the statement without re-reading the corpus.

## References (`src/parser/bibitem.py`)

- `\bibitem` → `BibEntry` (the `bibtex` columns + `raw`, `source`). `citation_key`, `year`, `doi`, `url`, arXiv ID are reliable; `authors`, `title`, `journal`, `entry_type` are heuristics per style (BibTeX `\newblock`, natbib labels, IEEE quotes, LNCS, Elsevier, hand-written).
- **Addition beyond the statement:** `.bib` files are read too. M1 keeps `.bib` but drops `.bbl`, so a BibTeX paper has its references only there. A `.bib` counts when the compilation path names it (`\bibliography`, `\addbibresource`) or embeds it (`filecontents`), and only entries the text cites are kept (all with `\nocite{*}`), as BibTeX prints only those. A named but absent `.bib` is reported in `missing_bib`.
- Conventions: `authors` = `"Given Family"` strings, `et al.` dropped; `journal` holds the journal or the proceedings/book title, `arXiv preprint arXiv:ID` for preprints; `url` is the arXiv abs page when only an arXiv ID is known.

## `gather` changes

`drop_disabled`: `\begin{comment}…\end{comment}` and `\iffalse…\fi` (nested conditionals counted, `\else` branch kept) are removed before reading, so their `\input`s are not followed and `expand` does not return their text. Unclosed blocks and `\let\ifdraft\iffalse` are left alone. Include depth is capped at 40 (TeX allows 15): a deeper chain raised `RecursionError`. Not followed, not in the statement: `\subfile`, `\import`, `\InputIfFileExists` — to be decided from `--scan` numbers on the real corpus.

## Verification

`src/tests/test_parser_run.py` (resume after a crash gives the same tables as an uninterrupted run, orphan shard, torn journal, two workers = one worker, lock, missing stage, error isolation, empty/missing versions), `test_bibitem.py` (12 reference styles, `.bib`, `filecontents`, fuzz), `test_gather.py` (disabled blocks, depth). The paper timeout needs POSIX signals; its test is skipped on Windows.
