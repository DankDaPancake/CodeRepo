# Colab notebooks and snapshot partitions

Goal: use Drive-only arXiv and hybrid notebooks, default hybrid to 1,000 original IDs for each of the four members, and generate reproducible only-v1 and multi-version JSONL snapshots from the assigned dataset.

1. Preserve the published hybrid branch implementation and progress reporting; remove Hugging Face notebook configuration and exercise checkout, resume, and safe run defaults.
2. Produce disjoint snapshot subsets with version validation, SHA-256 provenance and complete assigned-ID coverage; never commit raw dataset files.
3. Ensure the two group notebooks can use the subsets without mistaking missing records for the other group; validate the selection against signed-by-hash expected ID lists.
4. Verify tests and notebook syntax; push the reviewed branch and create a PR, explaining how to place generated inputs on Drive.
