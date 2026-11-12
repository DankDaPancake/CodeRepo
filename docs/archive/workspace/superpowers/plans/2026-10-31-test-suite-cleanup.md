# Test suite cleanup implementation plan

Approved scope: implement docs/review-test-overlap-9e6470b.md. Test-only change on refactor/test-suite-cleanup; no crawler/notebook edits, no dependency changes, no automatic commit/push/PR. Work in the existing checkout on a feature branch so the local environment remains usable; preserve existing stash.

1. RED: strengthen S2 Retry-After assertion to require two actual waits. Observe failure, fix helper's None/empty-list handling, rerun.
2. Merge four repeated scenarios, preserve every assertion; delete trial-path non-test. Parameterize scheduler initial decisions, gzip header names and rejected Range responses; retain all input scenarios.
3. Rename overstated tests to the behavior they prove; strengthen scheduler integration with real batch observations. Move shared fakes/builders into dedicated test helper modules and split checkpoint tests out of runner tests. Maintain every runtime/error/measurement scenario.
4. Review assertion preservation, full pytest, ruff lint/format, git diff --check. Record results and test-case count; explain changed count. Only test files may differ from base 9e6470b.

Baseline: 244 cases, 216 test functions, 27 test modules; full suite passed in preceding review. Regression boundary: S2 waits must be nonempty; missing scheduler use must change observed discovery batches; raw-folder roundtrip must retain no-ZIP/source/metadata/temp checks. Retain local-vs-remote locks, EOF-vs-exception resume, producer/crawler/parser roles, session-vs-chunk resources, CSV exports and all error-cleanup cases.

Review: self-contained test cleanup; independent reviewer availability previously failed with usage limit. Do not switch models/providers to work around that limit. Perform diff review and disclose no fresh independent review if it remains unavailable.
