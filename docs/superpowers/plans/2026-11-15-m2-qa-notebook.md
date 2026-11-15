# M2 QA Notebook Implementation Plan

**Goal:** Run complete, resumable QA on the existing M2 full-run output without rerunning or changing the parsing benchmark.

**Architecture:** A separate Colab notebook pins the QA code revision and validates the existing run identity and shard hashes. QA validates the paper-to-shard mapping, processes bounded batches and individual papers, checkpoints results independently, and exports a separate QA evidence bundle. Disk-backed storage is available for oversized partitions.

**Tech stack:** Python, PyArrow, SQLite, Colab, Google Drive and pytest.

## Design review: `check_tables`

The current implementation materializes every table as Python dictionaries, then builds global dictionaries, sets and adjacency lists. The observed output has 9,226,078 elements, 11,762,846 hierarchy rows and 842,436 bibtex rows. `SIGKILL` is compatible with memory exhaustion but does not prove it. Another risk is that the current root check iterates only versions already having roots, and its depth-first traversal lacks a visited set; the new checker must detect rootless versions and terminate on cyclic/corrupt graphs.

Alternatives considered:

1. Check each shard alone: fast and bounded by shard size, but fails to establish cross-shard uniqueness and can miss split papers. Insufficient by itself.
2. Put every element and edge in SQLite and perform joins/graph queries there: strong global semantics and bounded RAM, but can create a very large database, many random writes and long execution time. Keep as fallback for graph inputs that exceed a safe partition.
3. **Recommended hybrid:** stream projected Arrow batches and validate each table row against a small journal-derived paper-to-shard map and the unique paper prefix. Once these preconditions pass, check each paper's complete graph independently, releasing memory afterwards. If a paper is too large for the configured budget, spill its graph to local disk or stop with a clear incomplete result; never silently pass it.

The hybrid approach depends on verifying partition invariants, not assuming them from the journal. Scan all three tables, including a paper appearing only in hierarchy or bibtex; catch repeated IDs even where the claimed paper differs. Journal records are evidence of intended assignment, not proof of table contents. Columns needed are elements `(element_id, arxiv_id, kind)`, hierarchy `(arxiv_id, version, element_id, parent_id)` and bibtex `(arxiv_id, citation_key)`; avoid reading large `content` and bibliography text. Any SQLite fallback uses bounded transactions, a configurable cache/temp directory and free-space checks. Counts and diagnostic examples must be bounded; never accumulate unlimited errors in RAM.

**Ruling after examining the real journal:** it contains 200 shards, each with 100 distinct papers, with 20,000 distinct paper IDs overall. Use an in-memory paper-to-shard map as the normal global index, then validate every table row's ownership and the uniqueness of folder prefixes before checking complete paper graphs. This is justified only if the checker validates these invariants and rejects violations. Spill exceptionally large individual paper graphs to disk or report QA incomplete. A full SQLite node index remains a fallback, not a required default.

**Implementation note:** the current checker groups projected rows for one entire shard in memory, then checks each paper graph separately; it does not yet hold only one paper's rows at a time. It refuses any shard above 500,000 total rows, so this is a row-count bound, not a strict byte or per-paper memory limit. The largest reported real shard is below the cap; a measured single-shard pilot is recorded below. Revisit disk-backed grouping if actual peak memory or pathological input exceeds the available budget.

Graph semantics: for every version appearing in hierarchy require exactly one root; validate ownership/existence of each child and parent, duplicate edges and parent multiplicity; traverse with a visited set and detect cycles, unreachable nodes and unused elements. Check branch parent consistency across versions for the same paper, including the current document-parent normalization. Reconcile journal version statuses and output presence separately so a missing entire version cannot disappear from the roots check. Existing behavior on invalid data is a reference, not proof of correctness; improved checks are reported separately where they change prior behavior. Preserve existing report fields and clearly document new fields, diagnostic order and exit codes.

Performance targets are evidence gates, not promises: measure elapsed time, maximum RSS and peak local disk at increasing data sizes and on at least one unusually large paper. Test at corpus-scale row counts where feasible and perform a real-data pilot before recommending a full run. Record costs of Drive reads, hash verification and SQLite writes independently. If the index cannot fit disk, fail before publishing a successful report.

## Constraints

- Preserve the existing `m2-full-01` output, parser revision, session records, benchmark metrics and original evidence ZIP. QA timings are separate.
- Inputs are the 200 committed shards and journal, the hash manifest, and five original corpus roots where source comparisons require them. The recovered BBL data remains a separate parser input; QA reads the already-produced bibtex table.
- Never assume the current runtime or its local corpus survives. Reuse it only after verifying identities; provide a fresh-runtime path and avoid an unnecessary full Drive corpus restore where possible.
- The notebook tracks `main` for a new QA run and records its resolved SHA, separate from the parser SHA. No new branch unless explicitly requested.
- Bounded memory must be demonstrated on representative large inputs; do not promise a Colab runtime or wall time before measurement.

## Tasks

### 1. Protect and identify inputs

**Files:** `src/qa/` (new input helper), `src/tests/` (input tests), new `src/notebooks/arxiv_nhom1_m2_qa.ipynb`.

- [ ] Define a distinct QA run ID and output directory under the existing M2 run; do not overwrite benchmark or the previously exported ZIP. Record source run ID, parser and QA revisions, manifest and journal digests, shard list and hash manifest digest.
- [ ] Verify journal completeness, duplicate shard IDs, 200 expected committed shards for this run, and each referenced shard against its recorded file hashes. Reject missing, altered or extra relevant files and unexpected journal/output mismatches; show file/shard progress. Tests cover missing/corrupt shards and a changed manifest.
- [ ] Support verified local reuse in the existing runtime and an independent fresh-runtime restore with bounded concurrency, local-space checks and no repeated parser invocation. Do not automatically copy uncommitted shards. Test interruption and re-entry.

### 2. Bound table-check memory without weakening checks

**Files:** `src/qa/check_tables.py`, `src/tests/test_m2_pipeline.py`, new QA-specific tests.

- [ ] Establish small reference fixtures using the existing checker and literal expected failures. Cover cross-shard duplicate element IDs and bibtex keys, missing and cross-paper parents, multiple or missing roots, cycles, unreachable/unused elements, changed schema and duplicate papers across shards.
- [ ] Implement incremental reading of required columns and exact ownership checks using the validated paper-to-shard map. Do not infer uniqueness merely from shard boundaries. Check graph reachability, parent consistency and unused elements by paper after verifying that all of a paper's rows are accounted for; reject violations of the assumed partition rather than silently missing them. Provide bounded disk-backed fallback or an explicit incomplete result for an oversized paper.
- [ ] Produce an equivalent `check_tables.json` schema and counts; retain explicit diagnostics and exit status. Compare results against the old implementation on valid and corrupted small fixtures; add progress and safe QA-specific checkpoints for interruption/resume.
- [ ] Profile peak RSS, local disk and wall time using scaled representative shards and a large-paper edge case. Demonstrate memory does not grow with total corpus rows; if a single paper cannot fit the budget, spill its graph to disk or fail clearly, not silently skip it.

### 3. Bound structural audit and retain human audit

**Files:** `src/qa/audit_structure.py`, `src/qa/audit_sample.py`, corresponding tests.

- [ ] Process shard/paper/version incrementally, retaining only required columns, and stream `structure_audit.csv` to a QA-owned temporary file with resumable atomic checkpoints. Compare exact output and agreement counts against old code on multiple roots and versions.
- [ ] Restore or access source files only as needed using verified M1 checkpoint indexes; document and measure Drive tradeoffs. Include missing source, empty/no-root versions and interruption tests. Keep source comparisons distinct from table integrity.
- [ ] Retain the reproducible 30-paper sample with seed 2026 and existing `audit_sheet.csv` format. Produce materials for human review; do not treat an unfilled sheet as a passed human audit.

### 4. Notebook, publication and verification

**Files:** `src/notebooks/arxiv_nhom1_m2_qa.ipynb`, `docs/huong_dan_chay_m2_smoke_va_full.md`, notebook tests.

- [ ] Make separate cells for setup, identity verification, restore/reuse, table check, structural audit, sample draw and export; provide progress for all long operations, elapsed time and actionable failure messages. Each stage must be independently restartable and report complete/incomplete explicitly.
- [ ] Remove the `verify-guide` and `verify` QA cells from `src/notebooks/arxiv_nhom1_m2_parse_benchmark.ipynb`, replace them with a link to the separate QA notebook, and update notebook tests and documentation. Keep parser benchmark, session and export behavior intact; do not require or advertise QA artifacts as already present.
- [ ] Write QA outputs and a separately named QA evidence ZIP; do not silently replace `m2_evidence.zip` or official benchmark files. Provide an explicit later step to combine evidence while preserving original inputs and documenting QA revision and timings.
- [ ] Test notebook configuration, subprocess failures, interrupted/restarted QA and corrupted inputs. Run the full test suite and lint; compare representative outputs and record peak RAM and timing. Run a controlled real-data QA pilot before full QA, then run full QA against the existing 200 shards. Confirm reports and hashes on Drive, and distinguish automated checks from the manual audit.

## Open operational evidence

- The previous full parse reported 20,000 committed papers, 200 shards and return code 0. Drive folder presence and manifest entries were checked; hashes have not yet been independently reread in the new QA session.
- `SIGKILL` is consistent with memory pressure from the existing whole-corpus Python objects, but is not itself proof of an OOM kill. Actual full-run QA memory and speed remain to be measured.
- One public real-data shard (`shard-00000`, 100 papers) was downloaded locally and each of its three Parquet files matched the Drive hash manifest. A local Windows pilot, not Colab, reported 44,188 elements, 55,620 hierarchy rows and 4,119 bibtex rows in about 0.46 seconds with end-of-process RSS about 77 MB (not a peak measurement). The first pilot exposed valid repeated leaves under multiple parents; the checker was corrected and the same shard then reported no problems. This single shard is not representative evidence for full-run performance or correctness.
- Aggregating the published `m2_papers.csv` by shard gives a maximum 156,271 total element, hierarchy and bibtex rows (shard 125); none of the 200 shards exceeds the current 500,000-row cap. Largest single paper has 28,511 reported rows. These are parser-reported counts and must be reconciled with Parquet and actual peak memory; a row cap is not a byte or RAM limit.
- `shard-00125` was independently downloaded and its three Parquet hashes matched the Drive manifest. On this Windows machine, the existing and bounded checkers both returned identical clean reports (64,299 elements, 86,555 hierarchy rows, 5,417 bibtex rows; 100 papers). A 10 ms sampled process-tree RSS peak was approximately 254.8 MB for the old checker versus 106.3 MB for the new checker, with wall times 1.28 s and 0.96 s respectively. These are local single-shard observations, not Colab or full-corpus guarantees.
- A read-only local pilot downloaded all 200 output shards and verified each file against the Drive hash manifest. The bounded table checker reported 20,000 papers, 26,491 versions, 9,226,078 elements, 11,762,846 hierarchy rows, 842,436 bibtex rows and zero problems. On this Windows machine it took 102.2 seconds with approximately 159.3 MB sampled peak process-tree RSS. These are table checks only, not structural or manual QA, and are not Colab performance measurements. This pilot ran before the later journal-status validation was added; the recorded journal reports no failed paper or error versions.
- A second local 200-shard table run, including the later root-kind and leaf-parent checks, reported the same counts and no problems in 99.1 seconds. `inspect_run` separately matched all journal paper IDs to the configured assignment and the known 200-shard inventory. No full-corpus source comparison or human review has been run.

## Execution sequence for remaining work

**Current local state:** the QA notebook, input inspection/restore, bounded table checker and resumable structural audit have been wired together and exercised on a local end-to-end fixture. The original notebook links to the separate QA notebook. These changes remain uncommitted; real-data and Colab-scale validation, the remaining edge cases and final review are still required. Preserve all unrelated untracked workspace files.

1. **Input contract and safe restore.** Extend `src/qa/qa_inputs.py` and `src/tests/test_qa_inputs.py`: write failing tests for malformed records, duplicate shard IDs, colliding folder names, absent or extra shard paths, stale manifest and hash mismatch, and a torn last journal line. Add a read-only parser retaining per-paper version records and original byte digests; do not use `Journal.load()` on immutable Drive inputs because it may truncate a torn journal. Add hash-verified reuse/copy with bounded workers, temporary paths, atomic publication, disk-space checks and progress; test interruption and restart. Output a QA-specific identity manifest containing parser SHA, QA SHA, run ID, journal/manifest hashes and shard hashes.
2. **Partition validation.** Add `src/qa/check_tables_bounded.py` and `src/tests/test_check_tables_bounded.py`. First test a valid multi-shard fixture and invalid wrong-shard rows, duplicate paper IDs, mismatched element ID prefixes, cross-paper parents, and duplicate element IDs/bibtex keys across shards. Read projected columns in Arrow batches, validate all three tables against the full assignment map and prefix mapping, and stop with explicit failure if any invariant needed for per-paper isolation is false. Never assume journal alone proves table contents.
3. **Per-paper integrity.** Add failing fixtures for missing and multiple roots, no-root versions present only in journal, missing nodes/parents, duplicate edges, cycles, unreachable nodes, unused elements and inconsistent branch parents across versions. Implement a visited-set graph check with bounded diagnostics; reconcile journal status and version presence according to existing parser output conventions. Aggregate compatible `check_tables.json` fields and clearly label strengthened checks. Compare valid and intentionally corrupt fixtures with the current checker; for known old-checker omissions use independently specified expected outcomes. An oversized paper must spill to disk or terminate as incomplete, not pass.
4. **Progress and restart.** Write tests for interruption after a shard, changed input identity, stale or partial checkpoint and repeated execution. Store QA-only per-shard results atomically under the QA run ID; bind checkpoints to manifest, source journal, QA revision and settings. Resume only after revalidating input and checkpoint identities. Aggregate global results exactly once and report independent stage status and progress.
5. **Structural and manual QA.** Complete `src/qa/audit_structure.py` by streaming output with atomic, resumable per-shard results rather than `list(iter_audit(...))`; test multiple roots, missing source/version, source status and interruption. Choose verified local corpus reuse or verified on-demand source retrieval; do not silently compare against an unverified corpus. Keep `src/qa/audit_sample.py` deterministic at seed 2026 and 30 eligible papers and save the blank human-review sheet separately from automated results.
6. **Colab notebook and migration.** Create `src/notebooks/arxiv_nhom1_m2_qa.ipynb`, with CPU setup, distinct QA ID, source and QA SHA pinning, optional restore/reuse, staged verification, both audits, sample draw and separate QA export. Progress must be visible during hashing, table verification and structure audit. Remove `verify-guide` and `verify` from the parse notebook, replace with a QA notebook link, adjust `src/tests/test_m2_notebook.py`, add `src/tests/test_m2_qa_notebook.py`, and update `docs/huong_dan_chay_m2_smoke_va_full.md`. Preserve parser benchmark and original ZIP; report QA runtime independently.
7. **Verification and handoff.** Run all QA tests, the full test suite and Ruff; confirm notebook code cells compile and outputs are clear. On representative synthetic data, compare exact output and failures against the reference and measure peak RSS, local disk and wall time as row counts and single-paper size increase. Run a real-data pilot with verified shards before authorizing full QA; record observed costs and limitations. After full QA, verify output reports and QA evidence on Drive and leave human audit explicitly pending until filled. Do not claim a full run, bounded performance on Colab, or data integrity verification before those actions actually succeed.
