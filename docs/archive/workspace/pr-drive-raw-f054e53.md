## Change

Mirror completed arXiv corpus files and crawler journals as ordinary Drive files instead of ZIP checkpoint deltas. M2 can read the per-paper/version folders directly. Restore checks file hashes against `INDEX.json` and ignores stray temporary uploads.

This PR preserves the teammate's implementation at `f054e538640eae572c3e731b70e46f41183cc408` without rewriting or adding commits. It is opened as a draft because the following issues remain.

## Required before merge

- [ ] Pin the Colab notebook to the reviewed raw-folder implementation. It currently pins `8310f7eb6d244dae5ad244e4d4632604b57efb36`, which still uses ZIP checkpoints.
- [ ] Preserve a restorable committed generation if the runtime stops after replacing a mutable file but before publishing `INDEX.json`. Reproduction: save once, change `work/run.log`, interrupt the second save immediately before index publication, then restore into an empty directory. The old index remains unchanged but restore fails with `Restored file mismatch: work/run.log`.
- [ ] Align the Drive destination with the requested layout: `arxiv-nhom1/data/corpus` and `arxiv-nhom1/work`. The current runner writes under `arxiv-nhom1/runs/<RUN_ID>/`.

## Validation

- Offline suite on an independent snapshot of this exact commit: `239 passed`.
- Ruff lint and formatting checks passed in the preceding review of the same commit.
- The interruption reproduction above demonstrates a gap not covered by the existing passing tests.
- No live Colab or Google Drive validation has been performed.

The separate recovery changes in #27 are not included in this branch and should be reconciled before the final fullcrawl notebook is released.
