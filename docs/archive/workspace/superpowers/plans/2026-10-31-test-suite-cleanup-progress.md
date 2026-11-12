# Test cleanup — completed locally

Base: 9e6470b. Branch: refactor/test-suite-cleanup. No commit/push/PR requested or performed; previous stash preserved.

- Retry-After strengthened first: RED (`[] != [10.0, 10.0]`), helper distinguishes None from empty list, GREEN (9 reference tests). Header delay 10 seconds exceeds both deterministic exponential backoffs.
- Four repeated scenarios merged, all previous outcomes/assertions retained. Trial paths test removed. Scheduler decisions/gzip naming/Range restart parametrized with all existing scenarios retained.
- Checkpoint tests moved to test_checkpoints.py; FakeArxiv/client_for moved to helpers_arxiv.py; seed_version moved to helpers_benchmark.py. No test module imports another test module. FakeArxiv supports per-instance version maps so benchmark tests no longer mutate shared fixture globals.
- Scheduler integration strengthened to observe real discovery batches of sizes 1,1,2 and the four corresponding jobs. Consumer/path-predicate/final-checkpoint names changed to match the behavior they actually assert.
- Report's optional stronger assertions for every checkpoint phase and process-unique consumers were resolved by accurate naming, keeping the cleanup small; no new product guarantees added.
- Focused checks: 94 passed after merges; 45 passed after helper extraction and scheduler change.
- Full verification: pytest -q => 239 passed in 18.12s; ruff check src => passed; ruff format --check src => 68 files already formatted; git diff --check => passed (only expected Windows line-ending notices).
- Two in-memory mutation checks detected ignored S2 Retry-After and a scheduler fixed to batch size 1. No production source was edited for these checks.
- Final self-review checked assertion moves, imports, new helper/checkpoint files and test-only scope. No fresh independent review: the earlier reviewer invocation was unavailable due to a usage limit; no provider/model fallback was attempted.
- The original 244 -> 239 reduction is exactly four merged duplicate scenarios plus one removed non-test. Parametrization preserves input cases. No claimed runtime speedup or full mutation-coverage proof.
