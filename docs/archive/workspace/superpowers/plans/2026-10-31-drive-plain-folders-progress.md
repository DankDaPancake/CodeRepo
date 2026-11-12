# SDD ledger — plan: 2026-10-31-drive-plain-folders.md

Base source9ad1a70 (includes pendingPR27), Book356b203 (pendingPR4). Clean existing branches forked for this feature; no user data touched.
Ruling: honor exact root data/work layout rather than place corpus under runs/id; bind each Drive root to one run. Smoke roots separate from full root — prevents silent warm starts and mixed corpus, costs explicit folder selection.
Ruling: new backend does not duplicate source into ZIP or hidden object backups. Corpus files immutable and hash verified; corruption fails closed. Mutable diagnostics may be newer than committed corpus, while version/discovery journals are reconstructed from committed deltas — preserves useful attempt evidence without duplicating ever-growing logs in every generation.
Pre-flight: generation state feeds resumed journals; raw work/profile and telemetry feed audit/stats; final post-measurement report publication must update visible work/CSV without claiming time inside sampler.
Folder backend first8tests RED(no module)→GREEN. Orchestrator rootdata/work assertion RED→GREEN with backend switch. Extra safety regressions formissingDrive root/TEAM were RED→GREEN. Fullsuite255passed before2extra safetytests; focused37passed after them. Handoff config checks confirm smoke10/200 separate roots and full20k canonicalroot. Legacy ZIPtests remain unchanged.
