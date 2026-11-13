# M2 readiness through the start of the full run — Implementation Plan

> For implementers: use `executing-plans` task by task. This plan ends at the start of the official 20,000-paper run; completing the run and reporting its results are follow-up work.

**Goal:** Prepare, validate, and start a reproducible Colab CPU M2 run using the five M1 partitions and separately recovered BBL files.

**Architecture:** Read the five verified M1 corpus roots and the separate BBL recovery root through two input pointers, join by paper/version during parsing, and pin both inputs and code provenance. Never copy BBL files into the corpus. Keep original M1 corpus, its journals and its benchmark unchanged.

**Tech stack:** Python, pytest, PyArrow/Parquet, Google Colab CPU, Google Drive, Jupyter Book.

**Spec:** `docs/specs/0005-m2-runner.md`, course M2 statement https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/ and the decisions below. Verify latest checkout before edits. No new branch; preserve unrelated untracked files.

## Baseline and task list

- Existing: gather/normalize/hierarchy/references/dedup/writer, runner, benchmark, checkpoint sync, Colab notebook and QA utilities. Local targeted tests on 2026-11-13: 132 passed, 1 skipped (Windows); not a Colab or full-data run.
- Existing Book data: local Windows smoke 100 papers / 130 versions. No evidence yet of an official full M2 Colab run.
- Not ready: no external BBL input support for recovery output; incomplete input identity on resume; live Drive sync consistency and interrupted-session telemetry need verification; Colab smoke/resume not yet demonstrated.
- Accepted M1 snapshot scope: 20,000 IDs and 26,491 versions; `unavailable` remains unavailable, S3 v1 is an inference, and no metadata re-verification is planned. Recovery is a separate M2 input, never part of the M1 crawl benchmark.
- Recovery journal: 2,296 recovered versions, 1 unavailable, 2,332 recorded BBL files; only five file hashes independently checked so far. `recovered` does not mean parseable references.

## Global constraints and review focus

- Pin code SHA, all five checkpoint INDEX/MANIFEST identities and BBL recovery manifest/journal content hashes; pin all parser settings. Resume must refuse changed inputs, even when path and file size are unchanged.
- Never modify the original Drive corpus or its logs; keep the corpus and BBL inputs in separate roots. Preserve relative paths, reject unsafe names and symlinks, mismatched hash/size, missing or duplicate destinations, unexpected paper/version.
- No hidden or unmeasured parser sessions: hard runtime loss can discard in-memory measurements. Record incomplete sessions and distinguish their observed lower bounds; do not present incomplete totals as complete end-to-end.
- Drive sync while parser commits must not publish a journal referring to missing shards; restoration verifies shard integrity. Test concurrent commit, partial copy, corruption and resume.
- Multiple BBLs, TeX bibitems, unsupported biblatex BBL, empty or unparseable BBL require observable outcomes, not assumed success. S3 v1 chronology remains inferred; arXiv v1 is not asserted byte-identical to S3.

## 1. Baseline and test environment

**Files:** `src/parser/`, `src/benchmark/m2_sync.py`, `src/benchmark/m2_benchmark.py`, `src/notebooks/arxiv_nhom1_m2_parse_benchmark.ipynb`, `src/tests/`, `../arxiv-book/m2/`.

- [ ] Refresh remote refs and inspect local states, keep user files; use the merged main revision without making a new branch.
- [ ] Review current parser behavior against course M2: gathering, empty versions, hierarchy, normalization, reference extraction, cross-version dedup and three schemas. Document concrete gaps and their tests.
- [ ] Run M2 and QA tests in local environment and a Linux/Colab smoke; log versions and skips. Existing test success does not establish data readiness.

## 2. Pin and restore input

**Files:** notebook, `src/benchmark/checkpoints.py`, new `src/benchmark/m2_inputs.py`, new `src/tests/test_m2_inputs.py`.

- [ ] Define input manifest with full SHA-256 for each source `INDEX.json`, `MANIFEST.json`, recovery manifest and journal, immutable code SHA, expected 20,000 IDs, parser arguments and exact paths. Freeze it before processing; enforce equality on resume.
- [ ] Test missing/changed index, changed recovery journal, same-size input mutation and repeated roots. Fail before parse; do not trust path/size fingerprint alone.
- [ ] Restore five Drive checkpoints using existing hash verification, then check assigned IDs exactly and version inventory against journals. Report missing, extra or duplicate data and stop on unresolved discrepancy.
- [ ] Verify disk space for restored data, separate BBL input, work, output, checkpoint and safety headroom on both Colab and Drive; record observed sizes rather than promising an unmeasured output estimate.

## 3. Read BBL as a separate input during parsing

**Files:** create `src/benchmark/m2_bbl_input.py`, `src/tests/test_m2_bbl_input.py`; update `src/parser/run.py`, `src/parser/bibitem.py`, notebook, runner tests and `docs/specs/0005-m2-runner.md`.

- [ ] Provide two logical inputs in the notebook: `DATA_ROOTS` (the five M1 corpus roots) and `BBL_RECOVERY_DIR` (the recovery run root containing `versions.jsonl` and `files/`). The parser accepts `--bbl-recovery-dir PATH` as optional; without it preserve existing behavior. The roots may remain on Drive or be individually restored/copied to distinct local directories, with no BBL copied into any corpus directory.
- [ ] Implement `load_bbl_index(recovery_dir: Path) -> dict[tuple[str, int], list[Path]]`: parse the final recovery record for each `(arxiv_id, version)`, include only `recovered`, validate the journal and safe relative paths, verify each file's byte count and SHA-256, and produce a provenance report. Reject absent/corrupt files, traversal, links, duplicate paths and inconsistent records; report unavailable separately. Verify all 2,332 recorded files against the current journal, and reconcile every recovered key to exactly one existing corpus paper/version before parsing.
- [ ] Pass indexed paths through runner/worker to reference extraction for the matching `(arxiv_id, version)` only. Preserve existing TeX and `.bib` preference, and retain current local BBL behavior when external input is absent. Define and test deterministic precedence and explicit handling if local and external BBL coexist; do not silently merge conflicting inputs. Multiple recovery files stay associated with their original version and provenance.
- [ ] Test no matching external record, correct version lookup for multi-version papers, unavailable record, malformed journal, missing/corrupt/unsafe files, duplicate records and paths, concurrent workers, nested paths and no mutation of either source. Count eligible, verified, available and actually read files separately.
- [ ] Pin recovery journal and every recovered file's identity in the run manifest; on each new session re-verify the separate input before restoring M2 state. Resume must refuse changed data including same-size edits. Use a new run ID if either source changes; never resume an older un-enriched result. No source-folder union, staging overlay or corpus modification.

## 4. Validate BBL interpretation

**Files:** `src/parser/bibitem.py`, `src/tests/test_bibitem.py`, `src/tests/test_m2_pipeline.py`.

- [ ] Test real-shaped examples with TeX `\\bibitem`, named `.bib`, multiple BBLs, biblatex-style BBL and no parseable entries. Check fallback is used only when earlier sources yield no entries, and evaluate whether scanning all BBLs adds duplicate or unrelated references.
- [ ] Fix only confirmed errors, preserving documented priority and reference deduplication; record versions with BBL available, BBL actually read, and entries parsed separately. Test citation-key renaming and field union across versions.
- [ ] Check a small selection of recovered files manually against outputs; record findings and limitations, not a claim of universal metadata accuracy.

## 5. Safe checkpoints and trustworthy measurements

**Files:** `src/benchmark/m2_sync.py`, `src/benchmark/m2_benchmark.py`, `src/parser/run.py`, respective tests and notebook.

- [ ] Reproduce potential race: a shard commits after sync lists shards but before it copies `shards.jsonl`. Snapshot the committed journal first and publish only after all referenced shards are copied and verified; test injected concurrent commits and interrupted sync, plus corruption and restore.
- [ ] Persist session start and telemetry incrementally during the run; simulate abrupt process/runtime loss, mark truncated session incomplete and avoid labeling the result complete. Verify session and sample continuity on resume, avoiding double counting. Document observed lower bounds and setup exclusions.
- [ ] Test resume with changed manifest, changed same-size input, missing or corrupted shard, stale lock, interrupted restore and retry errors. Reject unsafe resume and ensure committed output is not silently rewritten.
- [ ] Verify sampler includes parser and descendants, accurately labels observed RSS/disk peaks, wall and output; separately report Drive sync competition and restore/BBL verification costs. Run focused tests, then full test suite.

## 6. Notebook preparation and Colab smoke

**Files:** M2 notebook, its tests, README and operating guide.

- [ ] Add configuration for five Drive paths and recovery folder, input validation and separate BBL input, safe resume, clear summary and disabled-by-default network/full-run flags. Gate QA/export until output exists. Pin exact revision and settings in run manifest.
- [ ] Provide a separate smoke run ID with selected real cases: recovered BBL, multiple versions, no TeX, unavailable, and BBL fallback. Confirm the three Parquet schemas, version statuses, provenance and reference counts; keep smoke results separate from official benchmark.
- [ ] On Colab CPU, deliberately interrupt smoke after a committed shard and after/during sync, restore to a fresh runtime and compare resulting tables/statuses to uninterrupted smoke; test POSIX timeout. Verify measurements acknowledge interruption and no input or output corruption.
- [ ] Record real Drive paths, access, free disk, installed package versions, elapsed restore and BBL verification, smoke errors and decisions. Resolve blockers before full execution; do not infer full-run duration from smoke as a guarantee.

## 7. Start full run

- [ ] Gate: all input integrity checks and BBL verification succeed; assigned ID set exactly 20,000 and version inventory reconciled; smoke and resume tests pass; benchmark records incomplete sessions correctly; no unresolved blocker in BBL handling or sync; sufficient disk/Drive space.
- [ ] Publish the reviewed code and notebook using the existing approved workflow, then open the exact merged revision on Colab CPU. Use a fresh full-run ID, preserve fixed inputs/configuration, start full parsing and record start time, revision, manifest and location of outputs.
- [ ] Confirm the first shard, durable sync and live status/telemetry; document how to resume with the same manifest. Stop this plan at a confirmed start; do not describe full parsing or quality checks as completed.
