# M1 Colab benchmark and MyST Book Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the verified M1 pipeline, provide one resumable Colab CPU notebook for all 20,000 assigned IDs, render it inside the existing two-chapter Book, and deliver one commit series and PR per repository.

**Architecture:** CodeRepo owns the executable notebook and a testable orchestration module; arxiv-book contains a generated, nonexecuting copy for reading and downloading. Crawl data remains outside Git. The Book renders CSV-based analysis separately from the operational Colab notebook.

**Tech Stack:** Python 3.12, existing requests/psutil crawler, Google Colab CPU, Google Drive checkpoints, Jupyter Book 2/MyST, pytest, Ruff.

**Spec:** User's four-item request of 2026-10-30; agreed single-notebook proposal in this conversation; `CodeRepo/docs/data_contract.md`; lecturer's requirement that the final benchmark cover all assigned IDs and the submitted Book contain M1 and M2.

## Baseline and boundaries

- Inspected CodeRepo baseline: `32c71ace76a2ac0a4c20aac6eb398c413908ff39`; 195 tests passed in the preceding verification.
- Inspected arxiv-book baseline: `8d2318c`; fetched origin/main has no divergence.
- Refresh both remote refs before execution and review new changes before creating branches.
- Proposed branches: CodeRepo `feat/m1-unified-colab-benchmark`; arxiv-book `docs/m1-benchmark-guide`.
- Execute changes in the existing checkouts on feature branches; never mix unrelated local files into commits. If isolation becomes necessary, obtain the workspace choice before creating a worktree.
- This is a plan only. Do not run a real crawl, delete an existing run, deploy GitHub Pages, or merge PRs as part of implementation.
- No Colab evidence archive has been supplied yet. Claims of 3.6 s/paper and 135 MB in 20 s remain observations, not verified final measurements.

## Global Constraints

- Final benchmark scope: all four assigned ranges, 5,000 IDs each, 20,000 unique IDs total; retain all discovered versions and required empty records.
- CPU-only Colab, no GPU or S3; keep the existing source endpoints and shared arXiv limiter.
- Preserve the existing data contract and CSV schemas; adding provenance files must not rename existing corpus fields or paths.
- Keep one executable entry notebook: `src/notebooks/arxiv_nhom1_crawl_benchmark.ipynb`, displayed as "arXiv Nhóm 1 — Crawl & Benchmark".
- A resumed run preserves corpus, journals, and all attempt profiles. Starting a new run uses a new identifier and refuses an existing target; never use `rm -rf OUT`.
- Keep at least three seconds between arXiv request starts, including process/chunk boundaries; only one coordinated group crawl at a time.
- All retry/fallback time stays in measured runtime. Log-derived backoff is diagnostic and must not be subtracted or added again to wall time.
- Keep the Book's existing language (English), two milestone chapter groups, output-free notebooks, and placeholder-data disclosure.
- Do not fabricate benchmark values, claim a full run has happened, or replace placeholder CSVs with sample data labeled as final.
- Colab cells render in the Book but must never execute during `jupyter book build --html --execute`.

## Added requirements: single crawl account, fixed Drive destination and runtime loss

- The user will designate one Google crawl account used by the members in shifts. Authorize the Colab Drive mount with that account; use `/content/drive/MyDrive/arxiv-nhom1` consistently. Do not implement shortcuts, Shared drive integration, service accounts, or cross-account authorization.
- The notebook must never silently create a substitute team folder when the expected folder is missing. Require a pre-existing team identity marker with a configured UUID, verify it after mounting, and test write/read access before crawling.
- Keep fixed run identifiers below the shared folder; M2 reads the restored corpus from the same run, not from whichever member's local runtime is still alive.
- Default checkpoint interval: 300 seconds, evaluated at completed-version boundaries, plus chunk boundaries and graceful stop. This requires an optional completed-version callback in `src/run_pipeline.py`; retain existing CLI behavior when no callback is configured.
- Persist the data and final records for completed versions only. Do not sync a version while it is still being extracted. A checkpoint includes matching metadata, references available at that boundary, version records, timing/attempt evidence, and a manifest of the data it commits.
- Publish immutable checkpoint generations: copy changed completed outputs, verify their sizes/hashes at the Drive destination, then publish that generation's completion record last. Keep the previous verified generation usable. Do not rely on a Drive rename or a single LATEST pointer being atomic.
- Restore the newest generation whose completion record and referenced files validate; ignore interrupted uploads, reject mismatched team/run identities, and rebuild only missing/uncommitted versions. Never re-crawl every completed paper after a timeout.
- A hard runtime kill cannot be handled by `finally`; only previously verified Drive checkpoints survive. The 300-second interval is a target, not a strict maximum loss: a long version or failed sync can exceed it. Show the age and coverage of the last verified checkpoint prominently.
- Reference failures remain retryable and separately tracked. Losing an in-progress version may require downloading that version again; Range recovery within one live process is not promised across a destroyed runtime.
- Run periodic checkpoint orchestration inside the profiled pipeline via the completed-version callback, so its CPU/RAM/disk usage is measured. Record checkpoint duration as an included component of pipeline wall time; avoid counting it again in session totals. Separately report any additional post-chunk/final sync outside the pipeline profiler.
- Freeze one validated M1 corpus/coverage manifest for M2 after full QA; parsing must not mutate source `.tex`/`.bib` files.
- Add offline failure-injection tests for kill-before-upload, kill-mid-upload, missing completion record, corrupted destination file, failed sync, wrong Drive folder, failed write preflight, and new-session resume on the same account. Manual Colab smoke test covers mount and Drive persistence.
- Checkpoint I/O and verification add real runtime. Record per-checkpoint duration, bytes transferred and completed-version count; report total included checkpoint time without subtracting it from the official end-to-end timing or counting it twice. Do not claim a fixed overhead percentage before measurement.
- Copy and verify only newly committed or changed completed outputs per checkpoint; avoid re-reading and hashing the full corpus on each 300-second checkpoint. Run full QA at finalization.

## Review Focus

1. Resume after interruption or partial Drive sync: never skip a version solely because its directory exists; require final journal status and validate restored results.
2. Accidentally selected sample, repeated IDs, or a final partial chunk: never label a sample or incomplete run as final.
3. Notebook opened on an unmerged branch: clone the same immutable code revision used to generate the notebook, not unrelated main code.
4. Colab notebook included in Book: build with execution enabled must not mount Drive, read Secrets, install crawler dependencies, or issue crawl requests.
5. Repeated attempts and profiler output: preserve attempt history, report interrupted attempts and sampling limits, and distinguish pipeline, sync, and session timing.

## Task 1: Unified run orchestration in CodeRepo

**Files:**
- Create `src/benchmark/__init__.py`, `src/benchmark/runner.py`.
- Create `src/tests/test_benchmark_runner.py`.
- Modify `src/run_pipeline.py` and `src/tests/test_run_pipeline.py` for the optional completed-version checkpoint callback described above.
- Modify `src/analysis/stats.py` and `src/tests/test_stats.py` only where correctness of final run aggregation requires it.

**Interfaces:** `BenchmarkConfig` defines mode (`sample`/`final`), run ID, owner, ranges, offset/count, chunk size, paths, and references setting. `plan_chunks(config)` produces exact range/offset/count units. `run_benchmark(config)` orchestrates the existing pipeline/profiler and returns a run-level result. Provide dependency seams for subprocess execution, clock, and checkpoint transport so tests are offline.

- [ ] Add failing tests for full scope (20,000 unique IDs), sample scope, invalid settings, exact final partial chunks, and refusal to overwrite a new-run target.
- [ ] Add failing tests for resumed completion, retained failed/interrupted attempt profiles, manifest mismatch, and nonzero child exit status.
- [ ] Implement full mode defaults with all four ranges, references enabled, offset zero, chunk size 100. Sample mode accepts a subset; both modes use the same orchestration.
- [ ] Persist a run manifest: code revision, selections, required IDs, dependency versions, Python/hardware information, UTC start, and attempt IDs. Verify immutable code/settings on resume; capture hardware per session because Colab may change machines.
- [ ] Give each chunk attempt a unique profile directory; explicitly enforce the inter-process request gap. Record pipeline duration, sync duration and actual session duration separately.
- [ ] Keep Drive shift state advisory: heartbeat while a chunk is running, refuse another active owner (including another session with the same display name), and require explicit takeover. Document that mounted Drive is not an atomic distributed lock.
- [ ] Checkpoint at chunk boundaries. If interrupted, stop/wait for the child before final sync, preserve evidence, and mark incomplete. Sync failure must not release the shift or mark the checkpoint complete.
- [ ] Restore corpus and work together; publish a checkpoint completion marker only after successful sync. Run QA before accepting restored completion/final status; report a partial checkpoint as incomplete rather than silently complete.
- [ ] Run targeted tests, then all existing tests. Expected: zero failures, no live arXiv/Drive access in tests.
- [ ] Commit: `feat: add resumable full-scope benchmark orchestration`.

## Task 2: One operational Colab notebook and evidence export

**Files:**
- Create `src/notebooks/arxiv_nhom1_crawl_benchmark.ipynb` by combining the two existing notebooks; modify `README.md`.
- Remove `src/notebooks/colab_benchmark.ipynb` and `src/notebooks/colab_crawl.ipynb` after migrating their functionality and replacing repository references.
- Create `src/tests/test_benchmark_notebook.py`.

**Interfaces:** Notebook uses Task 1's configuration and runner; it remains the single Colab entrypoint. End-of-run export includes a machine-readable coverage result and evidence ZIP.

- [ ] Add checks for output-free valid notebook JSON, explicit sample/final configuration, no destructive clean-start cell, pinned code checkout, and meaningful handling of subprocess failures.
- [ ] Add cells for CPU runtime instructions, editable config, repository setup, Colab Secrets, Drive mount/restore, run/stop, QA, report/export, final sync/release. New run and resume are explicit choices.
- [ ] Preserve profiler and `/usr/bin/time -v`; label process-tree RAM versus time-v wrapper RAM accurately. Explain sampling (RAM each second, disk periodically), excluded install time, and separately reported sync time.
- [ ] Full completion requires exact assigned coverage and final version statuses with correct directories. Report source QA and reference QA separately; incomplete references must not be concealed by source completion.
- [ ] Evidence ZIP includes manifest, coverage/QA reports, `versions.jsonl`, `discovery.jsonl`, `runs.jsonl`, `run_summary.json`, `failed.csv`, `run.log`, all profiles and exported Book CSVs. Exclude secrets and corpus contents.
- [ ] Add a short Colab preflight checklist and sample-first instructions. Actual web Colab/Drive functionality still requires a user-run smoke test and is not claimed from local tests.
- [ ] Run Ruff, notebook structure checks and full pytest suite. Check every former crawl-notebook reference.
- [ ] Commit: `feat: unify Colab crawl and benchmark notebook`.

## Task 3: M1 documentation in arxiv-book

**Files:** Modify `m1/index.md`, `m1/01-methodology.md`, `m1/04-discussion.md`, `m1/03-performance.ipynb`, `index.md`, `README.md`, and `references.bib` as needed.

**Interfaces:** Documentation describes the exact CodeRepo commit produced by Tasks 1–2; analysis pages continue to read existing CSV files.

- [ ] Document discovery batches/version metadata/OAI fallback, streaming extraction and format exceptions, Range recovery, 429/backoff, local and Drive resume, references, and the definition of complete source data.
- [ ] Correct stale `.part`-for-every-download text and the claim that interrupted transfers always use exponential backoff. Describe fail-fast discovery from PR #24 without promising it avoids network failures.
- [ ] Document full final coverage versus sample validation, per-ID versus per-version time, retry inclusion, timing boundaries, process-tree RAM, sampling limits, and run provenance.
- [ ] Distinguish implementation/tests from observations of the first 100 Dang IDs (`2604.20535`–`2604.20634`). Label 3.6 s/paper and 135 MB/20 s as unverified observations pending run evidence, or omit them from measured-results prose.
- [ ] Replace discussion TODOs with supported limitations and next steps. Keep final results explicitly pending and existing fake CSV notices visible on rendered data/performance pages.
- [ ] Check citations and preserve exactly the existing M1/M2 chapter groups.
- [ ] Commit: `docs: align M1 methodology with verified crawler behavior`.

## Task 4: Render the notebook inside the Book and build a preview

**Files:** Create `m1/arxiv_nhom1_crawl_benchmark.ipynb`, `scripts/sync_benchmark_notebook.py`, `scripts/check_benchmark_notebook.py`; modify `myst.yml`, `README.md`, and `.github/workflows/check.yml` as needed.

**Interfaces:** The sync script consumes a local canonical notebook plus its exact CodeRepo commit and generates the Book copy. Generated provenance and Colab/GitHub links name that commit. The checker validates provenance, output-free cells and skip-execution metadata without fetching arbitrary remote code during the Book build.

- [ ] Copy canonical notebook source into the Book with a generated provenance introduction, Colab launch link and downloadable source. Mark notebook metadata `tags: [skip-execution]` per MyST's documented ipynb behavior; do not hand-edit copied code cells.
- [ ] Link this notebook as a subsection within M1; keep M2 and its position intact. The rendered notebook is the requested embedded preview, not just an outbound link or iframe.
- [ ] Add checks that generated code cells match the recorded canonical input, outputs are empty, and execution is skipped. Demonstrate that Book build executes the CSV analysis notebooks but not Colab cells.
- [ ] Install Book build dependencies in a Book-specific environment, then run `jupyter book build --html --execute` using the environment's executable; Node is already present, Jupyter Book is not installed in the current CodeRepo environment.
- [ ] Inspect generated notebook page, navigation, code visibility, Colab link and download link. Deliver the absolute `_build/html/index.html` path and the notebook page path. Do not start a server or deploy Pages for this preview.
- [ ] Commit: `docs: embed reproducible Colab benchmark notebook in M1`.

## Task 5: Final checks, push and two linked PRs

- [ ] Fetch both main branches again and inspect any concurrent changes; incorporate them without discarding local work, rerun checks affected by those changes.
- [ ] CodeRepo: `python -m ruff check .`, `python -m ruff format --check .`, `python -m pytest`.
- [ ] Book: generated notebook check plus successful `jupyter book build --html --execute`; confirm no outputs, secrets or raw corpus are staged.
- [ ] Review all staged diffs. Use specific paths when staging and verify every commit.
- [ ] Push CodeRepo feature branch; open PR against main using available GitHub connector (gh CLI is currently unavailable). Immediately link the PR in the harness; state any linking failure.
- [ ] Pin Book's generated notebook/provenance to the final CodeRepo implementation SHA; push Book branch and open its PR, referencing the CodeRepo PR and SHA. Immediately link it in the harness.
- [ ] Deliver both PR URLs, final SHAs, check status and preview paths. Keep full crawl and measured final numbers pending. Do not self-merge or deploy the Book.

## Acceptance checklist

- [ ] One canonical runnable Colab notebook supports safe new runs, resume and exact full scope.
- [ ] Full mode covers every assigned ID and all discovered versions; partial work cannot masquerade as final.
- [ ] Evidence and timing remain auditable through retries, failed sync and resumed attempts.
- [ ] M1 prose matches code and separates reported observations from verified measurements.
- [ ] Book renders the operational notebook without executing it; CSV analysis still builds normally.
- [ ] Two milestone chapter groups, two reviewed commit series, two PRs, and a local HTML preview.

## Sources and unresolved evidence

- MyST execution: https://mystmd.org/guide/execute-notebooks
- MyST ipynb skip-execution metadata: https://mystmd.org/guide/notebook-configuration
- Local baseline code, notebook sources, Book CI and data-contract documents inspected on 2026-10-30.
- Needed later for quantitative M1 results: the user's Colab `bench_results.zip`, `versions.jsonl`, and exact CodeRepo revision.
- Drive sharing/shortcuts: https://support.google.com/drive/answer/7166529 and https://support.google.com/drive/answer/9700156
- Shared drive ownership: https://support.google.com/a/users/answer/7212025
- The lecturer explicitly requires full assigned coverage; a guarantee that a multi-session aggregate is accepted has not been supplied. Describe session aggregation transparently, without claiming one uninterrupted runtime.
