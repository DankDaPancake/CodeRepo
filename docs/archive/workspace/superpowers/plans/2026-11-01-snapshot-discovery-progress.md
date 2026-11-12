# Snapshot-first discovery — 2026-11-01

Branch: feat/snapshot-discovery, based on main 9e6470b. Previous uncommitted test cleanup preserved in stash@{0}; earlier folder work in stash@{1}.

Implementation: 69d8382. Notebook configuration/pin: eaa5649. Both local only, no push or PR performed.

Scope: provided snapshot seeds valid base-paper metadata and dates; missing/invalid records use existing API/OAI fallback. Versioned API requests enrich historical title/authors; null remains unknown. Coverage is frozen to the input snapshot. No HF backend, Kaggle download automation or existing Drive checkpoint redesign.

Index: one filtered JSONL subset for all benchmark IDs, checksum verified and checkpointed with work. Manifest pins source SHA-256; input/path/config/revision remain fixed on resume. Resume validates and reuses restored index. Child payload forwards index path. Preparation costs included in session sampler and discovery_time CSV. Initial manifest hashing is pre-session setup and disclosed as such.

Verification: first four snapshot tests RED (base API requested, spacing skipped, missing index builder), then GREEN. Index-preparation measurement RED 2 != 7, then GREEN. New tests cover no metadata network for one-version papers, historical-version-only queries and date preservation, API refusal without invented authors, missing/invalid records fallback, input identity on resume, corrupt index rebuild, child forwarding, orchestration with/without snapshot, and index measurement aggregation.

Full suite 257 passed in 20.31s. Ruff lint/format and diff whitespace checks passed. Notebook pin subsequently validated with 2 notebook tests and lint. Final working tree clean. Independent review unavailable in this session; self-reviewed integration, index hashing, provenance and timing scope. No live Colab or live arXiv crawl performed.

Real input validation: SHA-256 7063f0824386733e331be93f4338bd06058a16210195adb22454c11e11288f71; 20,000/20,000 assigned IDs valid, 26,491 versions, 14,913 single-version papers. Generated ignored data/metadata/assigned-snapshot.jsonl = 8,085,269 bytes. Local preparation observation 9.69 seconds (not a final Colab benchmark).

Next deployment step: publish branch before fresh Colab can fetch notebook CODE_REF 69d8382ad4704a7d72df8337de2009d9ce946c17; configure SNAPSHOT_PATH after local /content download; use new run ID. HF storage remains a separate implementation task.
