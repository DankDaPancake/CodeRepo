# Hybrid batch archive experiment

Goal: a separate Colab notebook based on the existing hybrid pipeline, selecting Dang offset 0/count 2500, with 100 original paper IDs per archive (including every required version). Start with tar.gz compression level 1 as an explicit experiment; no speedup claim before measurement.

1. Implement and test a verified batch packer. Preserve corpus paths, metadata/references, empty version directories, per-version status and file hashes. Final batches must pass source/reference QA; publish the archive only after verification.
2. User chose archive-only checkpoints plus logs/evidence. Implement fixed ID slots with partial snapshots during crawling and QA-complete final batches; never upload a raw corpus mirror.
3. Integrate the chosen contract with the existing benchmark runner and resume mechanism. Keep archive creation/verification/upload within the measured boundary; include staging in peak disk observations. Keep evidence and provenance separate from paper payloads.
4. Create a new notebook with a distinct RUN_ID and Drive destination, 100-paper archive size, unchanged original hybrid phase ordering, existing bulk paths, progress and CPU-only setup. Require publication of code before live Colab use; saved revision controls resume.
5. Run offline round-trip/corruption/interruption tests and existing regression checks. Document live smoke and timeout/resume checks required before the 2500-ID experiment. Do not commit or push in this work session.
