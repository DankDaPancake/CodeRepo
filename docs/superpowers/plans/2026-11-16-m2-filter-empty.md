# Filter empty-version roots from M2 output

- Verify completed source identity, journal and all shard hashes; refuse changed or overlapping paths.
- Filter only journal `empty` versions, verifying exactly one document root and no other edges for each. Preserve `no_root`, other elements and bibliography; refuse unexpected inputs.
- Create separate output and manifest, record source identity and resulting hashes; never overwrite a prior output.
- Validate the filtered tables using the bounded checker configured explicitly for rootless `empty` versions, while retaining the original journal statuses.
- Provide a Colab notebook with `RUN_FILTER=False`, pinned code, progress, and Drive output separate from the benchmark. Test mixed statuses, invalid roots and unchanged source before use.
