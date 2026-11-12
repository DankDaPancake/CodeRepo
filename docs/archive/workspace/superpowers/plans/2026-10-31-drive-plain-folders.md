# Plain Drive corpus implementation plan

User-approved spec: preserve the screenshots' root `arxiv-nhom1/data/corpus/<paper>/vN`, metadata/references and `arxiv-nhom1/work/profile` for direct M2 use. Measurement and resume remain supported. No crawl/discovery policy changes; Kaggle snapshot stays a pending feature.

Architecture: new folder checkpoint backend for new pinned runs; legacy ZIP backend remains for legacy revisions. Upload completed immutable corpus files once as ordinary Drive files, verify temporary uploads before rename, and publish a JSON generation record last. Records retain changed corpus hashes plus version/discovery state deltas. Mutable work logs/profiles mirror directly; restore reconstructs committed journals from generation records and preserves latest diagnostic work/telemetry. No ZIP corpus/checkpoint chain in new runs. Reports/evidence ZIPs remain optional exports.

Drive root binds to one run using work/manifest.json. Refuse mixed/unowned existing corpus/work. Smoke experiments use separate explicit Drive directories; full crawl uses the canonical arxiv-nhom1 root. Never delete/archive/migrate existing user Drive data automatically. Root data is immutable; corruption fails validation rather than silently claiming recovery from a nonexistent backup.

1. TDD folder backend: plain M2 paths, no ZIPs, unchanged files not recopied, verified partial-upload handling, missing source rejection, empty versions, canonical corruption, interrupted generation exclusion, committed-journal reconstruction, run binding, path safety.
2. Integrate runner: folder backend, immutable layout marker, final plain work/CSV publication after measurement/evidence export. Preserve full-session metrics and Drive-failure local rescue. Update offline orchestrator tests.
3. Update notebook pins, Book mirror/methodology and Vietnamese handoff guide to actual root layout and separate sample roots. Verify configs and build.
4. Full suite/lint, one fresh review per executing-plans, one regression fix pass, commits and PRs. Based on pending recovery PR27/Book4; no merge performed.

Ledger: 2026-10-31-drive-plain-folders-progress.md.
