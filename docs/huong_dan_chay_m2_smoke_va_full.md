# Running the M2 smoke and full parse on Colab

This guide starts after the M2 notebook changes have been merged into CodeRepo `main`. Both runs parse the five M1 partitions and read recovered `.bbl` files from a separate Drive folder. They do not crawl sources or change the M1 corpus or its benchmark.

## Before starting

1. Open the [M2 notebook on Colab](https://colab.research.google.com/github/hcmus-arxiv-nhom1/CodeRepo/blob/main/src/notebooks/arxiv_nhom1_m2_parse_benchmark.ipynb), save your own copy if prompted, and choose a **CPU** runtime.
2. Use a Google account that can access all five M1 run folders and the complete BBL recovery `run-01` folder. Add shared folders as shortcuts in My Drive if needed, and authorize Drive when prompted.
3. In the directory configuration cell, check `DRIVE_DIR`, the five `RUNS` paths, `BBL_RECOVERY_DIR` (the folder containing `versions.jsonl`, `candidates.json`, `summary.json` and `files/`), `M2_DRIVE_DIR` and `LOCAL_ROOT`. Keep the BBL folder separate from the corpus. Make sure Colab local disk and Drive have sufficient free space for the restored corpus, output and checkpoint copies.
4. For a **new** run, keep `REPO = "https://github.com/hcmus-arxiv-nhom1/CodeRepo.git"` and `CODE_REF = "main"`. The notebook resolves `main` to a commit SHA and saves it in the run manifest. On resume it uses that saved SHA even if main has advanced. Restart the runtime before changing revisions or rerunning setup after modules have loaded.

## Smoke: 1,000 papers

The default configuration is:

```python
RUN_MODE = "smoke"
SMOKE_LIMIT = 1000
SMOKE_OFFSET = 0
M2_RUN_ID = "m2-smoke-1000-01"
RESUME = False
RUN_M2 = True
CODE_REF = "main"
```

`RUN_M2` defaults to `False` in the notebook as a safety switch; set it to `True` when ready. Pick a new `M2_RUN_ID` if that Drive output already exists. Smoke selects the first 1,000 papers in stable folder/ID order starting at offset zero; this is a reproducible operational sample, not a random or necessarily representative sample. The preflight still checks all 20,000 assigned IDs and the complete BBL recovery journal.

Run the cells in order. Mount Drive when asked. The five M1 checkpoints are restored and verified before parsing; this can take a long time even for a smoke run. The restore bar counts **five runs**, not papers. Input verification follows; then the parser progress bar updates every **25 processed papers** and at the end. It shows committed papers already present when resuming, but paper progress can precede durable checkpoint publication. Warnings and errors remain visible.

After the benchmark finishes, review the status output, table checks and results under `M2_DRIVE_DIR/M2_RUN_ID/`. Confirm that `m2_papers.csv` contains 1,000 papers, review `m2_versions.csv` statuses and BBL/reference counts, and inspect the logs and `measurement_audit.json`. A zero process exit does not by itself prove every version parsed correctly. Smoke timing and output counts are not the official full-corpus benchmark.

Before starting full processing, exercise interruption and resume on a separate smoke run and compare its output and audit with an uninterrupted smoke run. Verify that the session/checkpoint state was synced to Drive; an interruption can lose work since the latest successful sync. Do not run two runtimes against the same run ID.

## Resume an interrupted run

1. Confirm that the previous runtime is stopped and no other runtime is writing this run ID.
2. On a fresh CPU runtime, open the same notebook and use the **same** `M2_RUN_ID`, `RUN_MODE`, smoke limit/offset, input paths and parser settings. Set `RESUME = True`; if the prior session is still marked active, set `PREVIOUS_SESSION_STOPPED = True` only after confirming it has stopped.
3. Run cells in order. The notebook uses the saved code SHA, checks the input identities, restores M1 data and the M2 checkpoint, then continues with uncommitted papers. Do not change the recovered BBL files or the M1 checkpoints during the run. If inputs or settings change, use a new run ID instead of resuming.
4. Read `measurement_audit.json`: when a runtime was lost, elapsed time and sampled peaks may be incomplete and are marked as lower bounds. An interrupted session cannot automatically provide measurements that were never synced.

## Full 20,000-paper run

Start only after reviewing the smoke output and interruption/resume evidence. Use a **new** run ID and configuration:

```python
RUN_MODE = "full"
M2_RUN_ID = "m2-full-01"
RESUME = False
RUN_M2 = True
CODE_REF = "main"
```

The smoke limit and offset are ignored in full mode. The input check requires the exact assigned 20,000 IDs, a complete BBL candidate/journal/summary reconciliation, verified file hashes and matching paper/version mappings. It stops on inconsistencies instead of treating them as successful parsing.

Run cells in order. The progress bar counts papers, not versions; each paper may contain several versions. Resource measurements include parser-side corpus and BBL verification. Restore is separately timed setup, while periodic Drive sync competes for resources and can affect wall time. The corpus `input_size` metric excludes the separate BBL folder on Drive; report its storage separately. After completion, inspect the run summary, version and paper CSVs, table and structure checks, random-paper audit and measurement audit before publishing results or declaring M2 complete. Export files remain under the full run's Drive directory.
