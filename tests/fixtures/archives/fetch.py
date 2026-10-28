"""Reproducible retrieval of the real package archives used by tests/test_real_archives.py.

usage: python -I tests/fixtures/archives/fetch.py [--check]

Downloads each archive from its pinned URL (fixed hosts, no redirects, size-capped), refuses it
unless the SHA-256 recorded in MANIFEST.json matches, and writes it next to this file. With --check
it only verifies the committed files. Archives are untrusted data: they are never extracted to disk
or executed here. Ordinary tests never use the network.
"""

import hashlib
import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
MAX_BYTES = 8 << 20
ALLOWED_PREFIXES = (
    "https://cloud.r-project.org/src/contrib/",
    "https://bioconductor.org/packages/",
)


def main(check_only: bool) -> int:
    manifest = json.loads((HERE / "MANIFEST.json").read_text(encoding="utf-8"))
    failures = 0
    with httpx.Client(
        timeout=30, follow_redirects=False, headers={"User-Agent": "R-Knowledge-MCP-fixtures/1.0"}
    ) as client:
        for entry in manifest["archives"]:
            path = HERE / entry["file"]
            if not path.is_file() and not check_only:
                if not entry["url"].startswith(ALLOWED_PREFIXES):
                    raise SystemExit(f"refusing unexpected host: {entry['url']}")
                response = client.get(entry["url"])
                response.raise_for_status()
                if len(response.content) > MAX_BYTES:
                    raise SystemExit(f"{entry['file']} exceeds {MAX_BYTES} bytes")
                path.write_bytes(response.content)
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            ok = actual == entry["sha256"]
            failures += not ok
            print(("ok      " if ok else "MISMATCH"), entry["file"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv))
