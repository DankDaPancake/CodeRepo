<!-- Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules. -->
# Spec 0005 — M2 runner, stage interfaces and reference extraction

- **Author:** Thiên (Member 1) · **Reviewers:** Đăng (owner of the M2 table schema), Tiến, Hiếu · **Status:** implemented; the stages below are the real modules
- **Date:** 01/11/2026 · **Branch:** `feat/m2-runner`

## Context

The M2 action plan (01/11) gives Thiên the shared runner ("one command for the whole corpus: versions without TeX recorded as empty, stop and resume"), `\bibitem` → BibTeX and the error hunt in `gather`. The runner is the glue of everybody's stages, so it fixes their call signatures here, in one place, for Gate 1 ("stable interfaces"). It does **not** change the three output tables (`elements`, `hierarchy`, `bibtex`) of the M2 schema: it only adds files under `work/`, which [`docs/data_contract.md`](../data_contract.md) §1 lists.

## Stage interfaces

Per paper, in order; `Rows` is `{"elements": [...], "hierarchy": [...], "bibtex": [...]}` of plain dicts, `VersionParse` is in `src/parser/model.py`.

| Stage | Module : function | Signature | Owner |
| --- | --- | --- | --- |
| cleanup + math | `src.parser.normalize:normalize` | `(text: str) -> str` | Tiến |
| hierarchy of one version | `src.parser.hierarchy:build_tree` | `(text: str) -> tree` (opaque to the runner) | Đăng |
| deduplication, IDs, rows of one paper | `src.parser.dedup:dedup` | `(arxiv_id: str, versions: list[VersionParse]) -> Rows` | Tiến |
| write a shard | `src.parser.writer:write_tables` | `(rows: Rows, out_dir: Path) -> None`, creates its files in `out_dir` | Hiếu |

`gather`, `expand` and `extract_references` (Thiên) run before `normalize`. `dedup` receives **every** version that has a folder, in order; a version without TeX arrives as `VersionParse(version, "empty" | "no_root" | "error")` with `tree=None`, so the writer can emit its root row (`#rootN`) and the version shows up in `hierarchy`. A `missing` version (no `vN/` folder) is not passed on.

**Empty version in `hierarchy`:** one `document` root per version (`<key>#rootN`, parent = the publication key), nothing below it. Implemented in `src/parser/dedup.py`.

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

## Implementation of the stages (2026-11-06)

`normalize`, `hierarchy` (+ `sentences`), `dedup` and `writer` are implemented in `src/parser/`; the rules are in the Book chapter "Parsing and standardization methodology". Decisions that other code relies on:

- **Kinds** (`elements.kind`): `document`, `chapter`, `section`, `subsection`, `subsubsection`, `paragraph`, `itemize`, `item`, `sentence`, `equation`, `figure` (a table is a `figure`).
- **IDs:** `<publication key>#<letter><n>` (`s` sentence, `e` equation, `f` figure, `h` heading, `l` list, `i` item), `#rootN` for the document of version N.
- **Matching across versions:** leaves by `(kind, content)`; a branch by `(kind, title, parent, rank among equal siblings)`, so that an element ID has one parent. References are renamed before the text is compared.
- **Parquet:** zstd, `kind` and `entry_type` dictionary-encoded, `authors` a list of strings, `year` and `version` int32.
- **`.bbl`:** the crawler keeps a `.bbl` only for a version with no `.bib` and no `\bibitem` (lecturer's answer, QA sheet, Milestone 1); `bibitem.extract_references` reads it when nothing else yields references.
- **New statistics columns:** `n_nodes`, `n_refs`, `n_bbl` per version and `elements_before`, `bibtex_before` per paper.

## The whole corpus: several runs, one corpus (2026-11-08)

The group crawl is five partitions (`only-v1-all`, `multi-{dang,hieu,thien,tien}-0000-4999`), each a Drive checkpoint with its own `data/corpus` and `work/versions.jsonl`.

- `--data-root` and `--crawl-work-dir` may be repeated. Papers are listed in folder-name order across the roots, so shards do not depend on the order of the roots; a paper in two roots stops the run (exit code 5).
- `--expect-assigned` stops (exit code 5) unless the papers found are exactly the IDs of `config.RANGES` (20,000); `work/assigned_check.json` lists the missing and the extra ones.
- `src.benchmark.m2_benchmark` adds the sessions of a resumed benchmark up (`m2_sessions.jsonl`, `session_id` in the time series) and reports `input_size` and `disk_max` (input plus the peak of output and work).
- `src.benchmark.m2_sync` copies the state to Drive in an order that is safe to interrupt (shards first, journal last) and restores it on a fresh runtime. The notebook `arxiv_nhom1_m2_parse_benchmark.ipynb` ties it together.
- The five runs were crawled by revision `ad03e0a`, which drops every `.bbl`: about one version in ten has no reference list. The group accepts this as a limitation and says so in the Book.


## Separate BBL input (in development)

`--bbl-recovery-dir` points to a recovery run with `versions.jsonl` and `files/`, separate from every M1 `--data-root`. The parser checks hashes and maps each recovered BBL by paper/version; it never copies BBL files into M1 corpus. References from TeX and `.bib` retain priority; the external BBL is a fallback when these yield no entries. A local and an external BBL on the same version is rejected. Recovered does not imply parseable references.

The enriched runner pins corpus content, recovery journal and parser settings in the work directory. Its checkpoint sync publishes an immutable journal snapshot only after its referenced shards are copied and hashed. Session loss is marked incomplete; actual Colab smoke and interruption tests remain pending. These changes do not alter M1 crawl benchmark measurements. See [the parser flow](../m2_parser_flow.md).
