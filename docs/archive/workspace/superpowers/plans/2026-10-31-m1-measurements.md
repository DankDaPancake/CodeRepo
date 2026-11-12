# M1 auditable measurements implementation plan

> Execute inline with executing-plans and TDD. User approved implementation on 2026-10-31.

Goal: establish trustworthy CPU Colab measurements before changing crawl performance.
Spec: ../../../../M1_requirements.md and the four approved measurement changes in conversation.
Constraints: no crawl policy/rate/retry changes; preserve smoke baseline; pinned revisions; disclose sampled peaks and lost intervals; no invented exact hard-kill duration.

Architecture: full-session sampler rooted at runner (includes child profiler/crawler), writing append-only local and remote telemetry independent of corpus checkpoints. Per-paper lifecycle events span discovery through required source/reference completion within each attempt, with retries retained. Core chunk metrics remain separate diagnostics. Session summaries aggregate full-session wall and sampled RSS/disk; interruption exports lower bounds, never certifies missing time as exact.

1. Timing correction: shared fake-clock tests for limiter wait and retries; elapsed covers full fetch minus measured limiter wait; process_version download total uses the resulting nonoverlapping components.
2. Session telemetry: test runner+descendant scope, time-weighted samples, durable interrupted-tail recovery and restore/phase coverage. Implement bounded-interval independent Drive snapshots and full-session summary. Record start before restore, finalize after final sync; report export overhead excluded explicitly.
3. Paper timings/export: test lifecycle start/completion including references, retained attempts, and success definitions. Add paper timing CSV and complete corpus summary (bytes/references/QA), session resource CSV/summary and timing audit. Never silently overwrite baseline or combine incompatible schemas.
4. Notebook/book/docs: display approved measurements and provenance, correct success mask and scope/units, pin tested implementation and regenerate mirror. Run full offline suite, lint, Book build, one independent final review; commit reviewable results. Do not run live crawl.

Review focus: interrupted remote writes/torn tails; resume with changed code; sampler concurrent checkpoints; missing reference metadata; profiler samples missing after hard kill.

Ledger: 2026-10-31-m1-measurements-progress.md.
