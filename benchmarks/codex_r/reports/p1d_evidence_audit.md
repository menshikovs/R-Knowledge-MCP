# P1-D D01 evidence access audit

Historical saved runs only. No source artifacts or scores were modified.

| Condition | Run ID | Discovery | Score | Client MCP calls | Server MCP calls | `list_package_functions` | Final package/version | Evidence status |
|---|---|---|---:|---:|---:|---:|---|---|
| enabled | `20261027T080622Z-16d73779` | enabled | 2/4 | 0 | 0 | 0 | termr 0.1.0 | insufficient_observability |
| disabled | `20261027T080923Z-f0bf06a8` | disabled | 4/4 | 15 | 15 | 0 | climenu 0.2.0 | insufficient_observability |

## Findings

- The treatment configured 13 tools; the server registered 16. The control configured 12 tools with the same 16-name registry. `list_package_functions` was configured only in the enabled run, but its observed call count was zero.
- The enabled answer selected `termr 0.1.0` against pinned `termr 1.0.1`; the source identity matches after host-case normalization, while the documentation identity differs from the pinned URL. Its recorded scorer result is 2/4.
- The disabled answer selected `climenu 0.2.0`, matching the pinned version and documentation identity. Its source is a version-specific official CRAN tarball URL, not the pinned package-page identity. Its recorded scorer result is 4/4.
- Historical response-level MCP records do not expose package versions and source/documentation URLs delivered to the agent. The enabled run has no observed MCP call; command execution and citations do not establish external page access. Source-access conclusions remain unknown.
- The optional session-configuration echo was added in telemetry schema 1.1 and was not present in the historical schema 1.0 records. Historical exposure is confirmed only from saved request/configuration metadata.
- Disabled raw counts are 15 client starts, 11 client successes + 4 client errors, and 11 server successes + 4 server errors: 15 attempts with 22 terminal successes and 8 terminal errors across two sources. The canonical count remains 15; client/server correlation is ordinal and unconfirmed.
- One observation per condition is exploratory and does not support a causal claim about discovery or scorer quality.

## Access classification

- enabled `termr` source URL present: true; access: `source_access_observability_unknown`.
- enabled `termr` documentation URL present: true; access: `source_access_observability_unknown`.
- disabled `climenu` source URL present: true; access: `source_access_observability_unknown`.
- disabled `climenu` documentation URL present: true; access: `source_access_observability_unknown`.
