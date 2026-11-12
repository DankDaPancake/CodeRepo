# M1 smoke audit — 200 Dang IDs

Evidence: the supplied `work/` and `book_csv/`, analyzed on 2026-10-31. Implementation revision `6c8c2b3632fab36513a9509a836891f856495411`. No crawler source changed and no live crawl performed for this audit.

## Outcome

- Scope: 2604.20535–2604.20734, 200 unique IDs, 279 versions, references enabled.
- QA: 200 source-complete papers, zero source/reference errors, complete sample, intact timing, two successful profiles.
- Versions: 266 `ok`, 12 `no_tex`, 1 `unavailable`. Empty/unavailable versions remain required records, not usable TeX.
- Pipeline profiles total 1,805.18 s (30 min 5.18 s); observed mean 9.026 s/requested ID. Session through final sync: 1,811.907 s.
- First chunk: 130 versions, profiler 895.38 s; second: 149 versions, 909.80 s. Per-version `total_s` mean decreased from 6.837 to 6.054 s. The small wall-time increase does not establish progressive degradation.
- Peak crawler-tree RSS 49.4 MB; observed peak watched disk 40.9 MB; corpus output 40.5 MB. Sum time-v user+system CPU is 24.78 s, about 1.37% of elapsed time on a one-core basis. The job is mainly waiting, not CPU-bound.
- Runtime: Python 3.13.18, 2 vCPUs, about 13.6 GB RAM, Linux. This differs from the documented Python 3.12 target and should be recorded when comparing samples.

## What consumed time

- Discovery: 7.6 s total, four successful metadata requests. No OAI fallback indicated in the request log.
- References: first batch finished in 6.5 s; second in 9.4 s; both overlapped much longer source processing. No reference tail bottleneck is indicated.
- Checkpoints: five periodic saves totaled 2.711 s; seven external saves totaled 1.427 s. All twelve saves totaled 4.138 s, about 0.23% of session elapsed time. This sample does not support blaming checkpoint overhead for the slowdown.
- arXiv: 445 requests, comprising 4 metadata and 441 source requests. Status totals: 292 HTTP 200, 62 HTTP 206, 90 HTTP 429, 1 HTTP 404.
- The cold successful path needs 4 metadata plus 279 source requests = 283 requests. The observed 162 extra requests consist of 90 rejected requests, 62 partial-content continuations and 10 replacement full-body requests.
- There were 69 cut-body warnings and ten restarts from byte zero. Seven restarts followed three Range rejections with 429; three hit the five-resume cap. At least 236,978,176 compressed body bytes (226 MiB) had already been consumed across those discarded attempts, inferred from logged offsets. This is not a complete wire-byte counter.
- Log-declared backoff totals 318.8 s over 83 waits. This is a diagnostic requested delay, already included in wall time and potentially overlapping baseline pacing; it is not an independent additive time bucket.
- The 134,663,506-byte version `2604.20623v2` took 86.631 s total in this run, with a discarded attempt at 84,934,656 bytes. Earlier observations of about 20 s cannot be validated from this run.

## Instrumentation defect confirmed

`HttpClient._fetch` starts its attempt timer before `_send`, and `_send` waits on the limiter. Returned `elapsed_s` therefore includes limiter waits, despite its documented exclusion. `process_version` then adds `wait_s` to form `download_s`, double-counting waits. In addition, `elapsed_s` covers only the final outer attempt whereas `wait_s` spans the whole fetch.

Offline reproduction using the same fake clock for both limiter and perf_counter: the second no-network call actually advances 3 s; it reports elapsed_s=3, wait_s=3, and elapsed+wait=6. The existing test used different fake/real clocks, masking this defect.

This also appears directly in the supplied records: summed `download_s` is 2,504.055 s while summed version `total_s` is only 1,790.864 s. Do not interpret `mean_transfer_extract_s` as pure transfer/CPU extraction time or use these overlapping fields to build a time-budget pie chart. Profiler wall time, time-v wall time, per-version total_s, and QA are still usable.

## Prioritized next work

1. Correct timing boundaries and add the shared-clock regression, plus log actual request start/end, requested/actual wait and Retry-After metadata. This fixes measurement, not transfer speed by itself.
2. Preserve a valid partial stream when Range requests receive 429: use bounded cooldown/retry on the same offset rather than discarding bytes after three rejections. Retain a total retry/deadline budget, a progress guard, and Content-Range validation.
3. Replace the fixed five-resume cap with a bounded policy that accounts for byte progress on large files. Never retry indefinitely or silently accept a mismatched range.
4. Evaluate adaptive pacing or a small fixed-pace pilot with the same IDs/configuration, rather than reducing the three-second minimum. Slower pacing may reduce 429 but can also increase overall time; benefit requires measurement. Respect Retry-After and the shared single connection.
5. Retain current checkpoint interval and extraction design for now. Increasing CPU workers, disabling references, or enlarging chunks is not supported as the first intervention by this evidence.

Preserve this baseline unchanged. A new candidate needs a new run ID and cold data, the same 200 IDs/all versions/references, coverage checks, and measurements of total time, rejected requests, Range recovery, restarts and discarded offsets. The one sample cannot establish a guaranteed speedup or full-20,000-ID runtime.

Policy source: https://info.arxiv.org/help/api/tou.html (one request per three seconds and one connection for legacy APIs, across controlled machines).
