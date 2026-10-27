"""Freeze the official CRAN resources that the D-block scorer accepts.

This is the only networked step of the D scorer. It issues read-only requests to
fixed CRAN hosts for the pinned candidates in ``verifier/candidates.json`` and writes
``verifier/official_resources.json``. Scoring itself (``knowledge_pilot.score``) only
reads that file and never opens a connection.

Run manually, review the diff, then commit:

    python -m benchmarks.codex_r.freeze_official_resources
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

PILOT = Path(__file__).resolve().parent / "knowledge_pilot"
CANDIDATES = PILOT / "verifier" / "candidates.json"
OUTPUT = PILOT / "verifier" / "official_resources.json"
CRAN = "https://cran.r-project.org"
ETHZ_MIRROR = "https://stat.ethz.ch/CRAN"
PACKAGE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9.]*\Z")
VERSION = re.compile(r"[0-9]+(?:[.-][0-9]+)*\Z")


def resource_plan(package: str, version: str) -> list[dict]:
    """Every URL shape the scorer may accept, with the check that proves it."""
    web = f"/web/packages/{package}"
    return [
        {"kind": "source", "form": "package_redirect", "url": f"{CRAN}/package={package}"},
        {"kind": "source", "form": "package_page", "url": f"{CRAN}{web}/index.html"},
        {
            "kind": "source",
            "form": "source_archive",
            "url": f"{CRAN}/src/contrib/{package}_{version}.tar.gz",
        },
        {"kind": "documentation", "form": "reference_pdf", "url": f"{CRAN}{web}/{package}.pdf"},
        {
            "kind": "documentation",
            "form": "reference_html",
            "url": f"{CRAN}{web}/refman/{package}.html",
        },
        {
            "kind": "documentation",
            "form": "reference_pdf",
            "url": f"{ETHZ_MIRROR}{web}/{package}.pdf",
        },
        {
            "kind": "documentation",
            "form": "reference_html",
            "url": f"{ETHZ_MIRROR}{web}/refman/{package}.html",
        },
    ]


def freeze(client: httpx.Client, candidates: dict) -> dict:
    tasks: dict = {}
    for task_id, packages in candidates.items():
        for package, expected in packages.items():
            version = expected["version"]
            if not PACKAGE_NAME.fullmatch(package) or not VERSION.fullmatch(version):
                raise ValueError(f"{task_id}/{package}: unsafe package or version")
            description = client.get(f"{CRAN}/web/packages/{package}/DESCRIPTION")
            description.raise_for_status()
            match = re.search(r"(?m)^Version:\s*(\S+)\s*$", description.text)
            if not match or match.group(1) != version:
                raise ValueError(
                    f"{task_id}/{package}: CRAN DESCRIPTION is {match and match.group(1)}, "
                    f"candidates.json pins {version}; update the pin deliberately first"
                )
            resources = []
            for item in resource_plan(package, version):
                response = client.head(item["url"])
                location = response.headers.get("location")
                redirect_ok = (
                    item["form"] == "package_redirect"
                    and response.status_code in {301, 302, 303}
                    and location == f"{CRAN}/web/packages/{package}/index.html"
                )
                if response.status_code != 200 and not redirect_ok:
                    raise ValueError(f"{item['url']}: unexpected HTTP {response.status_code}")
                resources.append(
                    {
                        **item,
                        "http_status": response.status_code,
                        "redirect_to": location if redirect_ok else None,
                    }
                )
            tasks.setdefault(task_id, {})[package] = {
                "resource_version": version,
                "description_version": match.group(1),
                "resources": resources,
            }
    return {
        "schema_version": 1,
        "purpose": "Offline allowlist for the D scorer; official CRAN resources only.",
        "generated_by": "benchmarks/codex_r/freeze_official_resources.py",
        "verified_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tasks": tasks,
    }


def main() -> int:
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    with httpx.Client(
        follow_redirects=False, trust_env=False, timeout=httpx.Timeout(30.0)
    ) as client:
        frozen = freeze(client, candidates)
    OUTPUT.write_text(json.dumps(frozen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} ({sum(len(p) for p in frozen['tasks'].values())} packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
