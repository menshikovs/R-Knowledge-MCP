# Upstream monitoring

`.github/workflows/upstream-smoke.yml` runs at 06:17 UTC daily on the default
branch and supports `workflow_dispatch` from the Actions tab. The workflow uses
read-only `contents: read` permission and runs separately from pull-request CI;
upstream downtime must not block unrelated source changes. A failed required
check makes the workflow fail. The checks detect changes at selected URLs and
do not guarantee that sources will remain available.

The script checks only fixed official HTTPS routes:

- CRAN's canonical `src/contrib/PACKAGES` index and the `ggplot2` DESCRIPTION.
  It verifies the package identity and that DESCRIPTION's version matches the
  current index.
- Bioconductor's current `/config.yaml`, then software, annotation and
  experiment `PACKAGES` indices for the release named by that configuration.
  It checks representative package identity/version records (`DESeq2`,
  `org.Hs.eg.db` and `airway`) without downloading archives.
- Shiny's reactivity, modules and async/nonblocking documentation pages.
- Positron's interpreter and R installation pages.
- Quarto's R computation and project documentation pages.

Context7 and GitHub are not queried, so the job needs no API keys and consumes
no third-party API quota. Requests reject redirects, disable environment proxy
configuration, use an eight-second HTTP timeout and a ten-second request
deadline, accept at most four concurrent requests, and cap bodies at 2 MiB for
documentation, 16 MiB for package indices and 1 MiB for Bioconductor config.
Only metadata and HTML pages are fetched; no package archive is downloaded or
executed.

Run the same live checks locally after installing the project with
`python -m pip install .`:

```sh
python scripts/smoke_upstream.py
```

Each output line is a JSON diagnostic with source identifier, check name,
success/failure, official URL and UTC timestamp. Failures include a category
and a sanitized message:

- `upstream_unavailable`: the upstream request failed.
- `redirect_introduced`: the canonical URL now redirects; redirects are never
  followed.
- `unexpected_http_status`: the source returned a non-success HTTP status.
- `invalid_response_body`: content type, encoding, size, syntax or topic content
  did not meet the check's expectations.
- `metadata_identity_mismatch`: a package was missing from the expected index,
  or its identity/version did not match.
- `network_timeout`: the bounded request timed out.
- `local_configuration_error`: the check URL/size or local HTTP client setup
  violated its fixed policy.
- `internal_smoke_error`: an unexpected script error occurred; only its
  exception type is reported.

The unit suite tests this logic exclusively with `httpx.MockTransport`; it does
not contact live sources. A green mocked suite therefore does not assert live
availability. Investigate a failed scheduled run using its Actions log and
source/check fields before concluding that application code is at fault.
