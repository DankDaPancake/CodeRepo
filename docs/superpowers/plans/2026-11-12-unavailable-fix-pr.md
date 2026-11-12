# Fix unavailable recovery and publish

**Goal:** Stop retrying when arXiv blocks the client and publish the recovery work for review.

- [ ] Add regression: BlockedError stops immediately, persists an inconclusive record and a subsequent resume retries it; no other paper is requested during the blocked run.
- [ ] Fix handling without swallowing BlockedError in both retry and downloader; ensure partial data isn't marked complete.
- [ ] Verify metadata/retry tests, actual evidence selection and notebook packaging; run full tests.
- [ ] Bring the branch up to date with origin/main while preserving unrelated untracked files; commit only recovery work, push and create a PR.
