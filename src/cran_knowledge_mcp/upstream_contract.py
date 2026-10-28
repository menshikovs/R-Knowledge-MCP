"""Nightly contract checks of Function Discovery and documentation against real upstream data.

The checks drive the project's own service layer (fixed CRAN/Bioconductor routes, explicit HTTP
timeouts, bounded retries, byte limits, no redirects, no caller URLs) over a small package sample
and assert structural invariants - never exact export or alias lists, which legitimately change
upstream. Each package ends as one of:

  pass          every invariant held;
  fail          an invariant was violated: a regression in this code (or a contract change);
  inconclusive  the upstream source was unavailable, rate limited, missing or inconsistent with its
                own index, so the invariants
                could not be evaluated. This is an outage signal, not a regression.

Exit status: 0 all pass, 1 at least one fail, 2 no fail but at least one inconclusive. Nothing
here edits source, expectations or benchmark evidence, and no credentials are read or recorded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import sys
import time
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from urllib.parse import urlsplit

from .function_discovery import COMPLETENESS
from .http import CranHTTP, make_client
from .parsers import DIAGNOSTIC_CLASS
from .service import KnowledgeService, bounded

SCHEMA_VERSION = 1
SAMPLE = (
    ("cran", "cluster"),  # mixed Rd encodings, useDynLib(.registration = TRUE)
    ("cran", "R6"),  # S3method() on another package's generic
    ("cran", "MASS"),  # S3 methods, native routines, large documentation set
    ("cran", "rpart"),
    ("bioconductor", "BiocGenerics"),  # S4 exports in the current release
)
ALLOWED_HOSTS = {"cran.r-project.org", "bioconductor.org"}
# Only conditions that originate upstream. `invalid_source` and `source_too_large` are produced by
# this project's own bounded parsers and limits (a parser regression or a package outgrowing a
# limit), so they are failures to investigate, never "inconclusive".
UPSTREAM_CODES = frozenset(
    {
        "source_unavailable",
        "rate_limited",
        "not_found",
        "package_not_found",
        "checksum_mismatch",  # archive differs from the repository's own index
        "version_mismatch",  # archive/page differs from the index
    }
)
PACKAGE_DEADLINE_SECONDS = 150
MAX_PAGES = 100
MAX_DOCS_SAMPLES = 3
SNAPSHOT = re.compile(r"[0-9a-f]{64}\Z")


class Inconclusive(Exception):
    """The upstream could not supply what the invariants need."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


class Checks:
    """Collects named invariants for one package; a violated invariant never raises."""

    def __init__(self):
        self.items: list[dict] = []

    def check(self, name: str, ok: bool, detail=None) -> bool:
        self.items.append(
            {"name": name, "ok": bool(ok), **({} if detail is None else {"detail": detail})}
        )
        return bool(ok)

    @property
    def failed(self) -> list[dict]:
        return [item for item in self.items if not item["ok"]]


def ensure(result: dict, step: str) -> dict:
    """Return a successful result; classify an error as upstream outage or as a failure."""
    error = result.get("error")
    if error is None:
        return result
    if error.get("code") in UPSTREAM_CODES:
        raise Inconclusive(error["code"], f"{step}: {str(error.get('message'))[:200]}")
    raise AssertionError(f"{step}: unexpected error {error.get('code')}")


def swap_separators(version: str) -> str:
    return version.replace("-", ".") if "-" in version else version


def trusted_source(source: dict) -> bool:
    url = urlsplit(source.get("source_url") or "")
    return (
        url.scheme == "https" and url.hostname in ALLOWED_HOSTS and bool(source.get("checked_at"))
    )


async def collect(api: KnowledgeService, repository: str, package: str, extra: dict):
    """Every discovery page (bounded). Returns (first_page, aliases, exports)."""
    first, aliases, exports, snapshot, offset = None, [], [], None, 0
    for _ in range(MAX_PAGES):
        page = ensure(
            await bounded(
                api.list_package_functions(
                    package, repository, limit=50, offset=offset, snapshot=snapshot, **extra
                )
            ),
            "list_package_functions",
        )
        first = first or page
        snapshot = page["snapshot"]
        aliases.extend(page["aliases"])
        exports.extend(page["exports"])
        if page["next_offset"] is None:
            return first, aliases, exports
        offset = page["next_offset"]
    raise Inconclusive("too_many_pages", f"more than {MAX_PAGES} pages")


async def check_package(
    api: KnowledgeService, repository: str, package: str, checks: Checks, out: dict
):
    extra = {}
    search = ensure(await bounded(api.search_packages(package, repository=repository)), "search")
    top = search["results"][0] if search["results"] else {}
    checks.check("search_returns_the_package_first", top.get("package") == package)

    first, aliases, exports = await collect(api, repository, package, extra)
    version = first["package_version"]
    out.update(
        package_version=version,
        bioc_version=first.get("bioc_version"),
        archive_sha256=first["archive_sha256"],
        discovery_checked_at=[s["checked_at"] for s in first["sources"]],
        source_urls=[s["source_url"] for s in first["sources"]],
        completeness=first["completeness"],
        verification_status=first["verification_status"],
        counts={"exports": len(exports), "aliases": len(aliases)},
        diagnostics=sorted({d["code"] for d in first["diagnostics"]}),
    )
    checks.check("identity", first["package"] == package and first["repository"] == repository)
    checks.check("snapshot_token", bool(SNAPSHOT.match(first["snapshot"])))
    checks.check("archive_digest", bool(SNAPSHOT.match(first["archive_sha256"])))
    checks.check(
        "provenance_hosts", all(trusted_source(s) for s in first["sources"]), first["sources"]
    )
    checks.check("completeness_known", first["completeness"] in COMPLETENESS, first["completeness"])
    checks.check(
        "status_matches_completeness",
        (first["verification_status"] == "verified")
        == (first["completeness"] in {"complete", "complete_with_diagnostics"}),
        [first["verification_status"], first["completeness"]],
    )
    checks.check(
        "diagnostic_classes_follow_the_table",
        all(
            d["class"] == DIAGNOSTIC_CLASS.get(d["code"], "incomplete")
            for d in first["diagnostics"]
        ),
    )
    checks.check(
        "unverified_has_a_limiting_issue",
        first["completeness"] in {"complete", "complete_with_diagnostics"} or bool(first["issues"]),
    )
    resolution = first["version_resolution"]
    checks.check(
        "version_resolution",
        resolution["resolved"] == version
        and resolution["match"] == "not_requested"
        and resolution["verified_for_requested_version"] is None,
        resolution,
    )
    checks.check("documentation_surface_not_empty", len(aliases) >= 1)
    checks.check("callability_not_claimed", first["callability"] == "not_checked")
    if repository == "cran":
        checks.check(
            "cran_archive_checksum_verified",
            first["source_verification_level"] == "archive_checksum_verified",
        )

    # Documentation agrees with discovery on identity, version and source.
    for alias in [aliases[i] for i in sorted({0, len(aliases) // 2, len(aliases) - 1}) if aliases][
        :MAX_DOCS_SAMPLES
    ]:
        docs = ensure(
            await bounded(
                api.get_versioned_function_docs(
                    package,
                    alias["name"],
                    repository=repository,
                    bioc_version=first.get("bioc_version"),
                )
            ),
            f"docs:{alias['name']}",
        )
        checks.check(
            f"docs_agree:{alias['name']}",
            docs["package_version"] == version
            and docs["version_scope"] == first["version_scope"]
            and docs["version_resolution"]["resolved"] == version
            and ("\\alias" in docs["text"] or "\\name" in docs["text"] or docs["offset"] > 0),
        )
        if alias["documentation_topics_complete"]:
            checks.check(
                f"docs_topic_listed:{alias['name']}",
                docs["archive_member"] in alias["documentation_topics"],
            )

    # The version contract against the real index.
    spelled = swap_separators(version)
    probe = ensure(
        await bounded(
            api.list_package_functions(
                package, repository, first.get("bioc_version"), spelled, limit=1
            )
        ),
        "equivalent spelling",
    )
    checks.check(
        "equivalent_spelling_accepted",
        probe["package_version"] == version
        and probe["version_resolution"]["match"]
        == ("identical" if spelled == version else "equivalent"),
        [spelled, version],
    )
    for tool, call in (
        (
            "discovery",
            api.list_package_functions(
                package, repository, first.get("bioc_version"), "0.0.1", limit=1
            ),
        ),
        (
            "docs",
            api.get_versioned_function_docs(
                package,
                aliases[0]["name"],
                repository=repository,
                bioc_version=first.get("bioc_version"),
                package_version="0.0.1",
            ),
        ),
    ):
        refused = await bounded(call)
        error = refused.get("error") or {}
        checks.check(
            f"historical_version_refused:{tool}",
            error.get("code") == "requested_version_unavailable"
            and error.get("substituted") is False
            and error.get("reason") == "historical_versions_not_supported"
            and error.get("available_package_version") == version
            and "text" not in refused
            and "aliases" not in refused,
            error.get("code"),
        )

    if package == "cluster":
        names = {a["name"] for a in aliases}
        if "plantTraits" in names:
            docs = ensure(
                await bounded(api.get_versioned_function_docs("cluster", "plantTraits")),
                "plantTraits",
            )
            checks.check(
                "cluster_mixed_encoding_resolved",
                docs["rd_encoding"]["encoding"] != "",
                docs["rd_encoding"],
            )
        checks.check(
            "cluster_registration_is_not_limiting", first["verification_status"] == "verified"
        )


async def run_package(api, repository: str, package: str) -> dict:
    started = time.perf_counter()
    checks, out = Checks(), {"repository": repository, "package": package}
    try:
        await asyncio.wait_for(
            check_package(api, repository, package, checks, out), PACKAGE_DEADLINE_SECONDS
        )
        status = "fail" if checks.failed else "pass"
    except Inconclusive as exc:
        status, out["inconclusive"] = "inconclusive", {"code": exc.code, "detail": exc.detail}
    except TimeoutError:
        status, out["inconclusive"] = (
            "inconclusive",
            {"code": "timeout", "detail": "package deadline"},
        )
    except AssertionError as exc:
        status = "fail"
        checks.check("no_unexpected_error", False, str(exc)[:300])
    except Exception as exc:  # a crash is a regression signal, reported without a traceback dump
        status = "fail"
        checks.check("no_crash", False, f"{type(exc).__name__}: {str(exc)[:200]}")
    out.update(status=status, checks=checks.items, seconds=round(time.perf_counter() - started, 2))
    return out


async def run(api: KnowledgeService, sample=SAMPLE) -> dict:
    started = datetime.now(UTC)
    results = [await run_package(api, repository, package) for repository, package in sample]
    counts = {
        name: sum(r["status"] == name for r in results) for name in ("pass", "fail", "inconclusive")
    }
    try:
        version = importlib_metadata.version("cran-knowledge-mcp")
    except importlib_metadata.PackageNotFoundError:
        version = None
    return {
        "schema_version": SCHEMA_VERSION,
        "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_version": version,
        "git_sha": os.environ.get("GITHUB_SHA"),
        "python": platform.python_version(),
        "sample": [list(item) for item in sample],
        "summary": counts,
        "outcome": "fail"
        if counts["fail"]
        else "inconclusive"
        if counts["inconclusive"]
        else "pass",
        "results": results,
    }


def exit_status(report: dict) -> int:
    return {"pass": 0, "fail": 1, "inconclusive": 2}[report["outcome"]]


def markdown_summary(report: dict) -> str:
    lines = [
        f"### Upstream contract: {report['outcome']}",
        "",
        "| repository | package | version | status | seconds |",
        "|---|---|---|---|---|",
    ]
    for r in report["results"]:
        lines.append(
            f"| {r['repository']} | {r['package']} | {r.get('package_version', '-')} "
            f"| {r['status']} | {r['seconds']} |"
        )
        for item in r["checks"]:
            if not item["ok"]:
                lines.append(f"|  | ↳ failed: `{item['name']}` | | | |")
        if r.get("inconclusive"):
            lines.append(f"|  | ↳ upstream: `{r['inconclusive']['code']}` | | | |")
    return "\n".join(lines) + "\n"


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nightly upstream contract checks.")
    parser.add_argument("--output", default="upstream-contract-results.json")
    args = parser.parse_args(argv)
    async with make_client() as client:
        report = await run(KnowledgeService(CranHTTP(client)))
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    summary = markdown_summary(report)
    print(summary, file=sys.stderr)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(summary)
    print(json.dumps({"outcome": report["outcome"], **report["summary"]}))
    return exit_status(report)
