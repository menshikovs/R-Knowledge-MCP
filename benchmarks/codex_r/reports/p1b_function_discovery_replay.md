# P1-B offline function discovery replay

Run: 20261026T104750Z-f78eabf1

- Requests: 59
- Preserved identities: 42
- Evaluated: 0
- Source fixtures available: 0
- Excluded missing identity: 17
- Excluded missing archive: 42

Historical improvement is unmeasured while historical_metrics is null.
Replay compares literal docs plus existing hints against proactive
discovery and exact alias/topic retrieval. Fuzzy output is never a docs success.
No historical files, task prompts, scorer or B1 descriptions were changed.

## Reproduce

Set PYTHONPATH=src and run:
python -m benchmarks.codex_r.replay_function_discovery
Supply --fixture-manifest PATH when verified local archives are available.

Manifest fixtures require repository, package, package_version, source_url,
upstream_checked_at, fixture_kind (real_pinned_source/synthetic_test),
archive_path/archive_sha256 and index_path/index_sha256. Paths are operator-local;
only the fixed CRAN archive URL is accepted. Both bodies are digest-checked,
then the actual provider verifies index/DESCRIPTION/checksum through MockTransport.
No automatic download or live fallback exists.

- A fuzzy suggestion alone is never counted as prevented docs_not_found.
- Baseline already returned verified available_aliases/closest_aliases.
- Task reference scope does not reconstruct B1 resolved source version.
- Synthetic fixture measurements are not historical B1 improvements.
- No agent behavior or final answer improvement is measured by retrieval replay.
