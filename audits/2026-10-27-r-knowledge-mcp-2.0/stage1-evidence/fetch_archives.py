"""Download the pinned CRAN source archives of the audit's 30-package sample (read-only, bounded).

usage: python -I fetch_archives.py <sample.json> <out_dir>
Writes <out_dir>/<pkg>_<version>.tar.gz and manifest.json (url, sha256, bytes, retrieved_utc).
Archives are untrusted data: they are only saved, never extracted or executed here.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

MAX_BYTES = 40 << 20
BASES = ("https://cloud.r-project.org/src/contrib/", "https://cloud.r-project.org/src/contrib/Archive/{pkg}/")


def main(sample_path: str, out_dir: str) -> int:
    sample = json.loads(Path(sample_path).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "R-Knowledge-MCP-stage1/1.0"}) as client:
        for row in sample:
            pkg, version = row["pkg"], row["version"]
            name = f"{pkg}_{version}.tar.gz"
            for base in BASES:
                url = base.format(pkg=pkg) + name
                response = client.get(url)
                if response.status_code == 200 and len(response.content) <= MAX_BYTES:
                    (out / name).write_bytes(response.content)
                    manifest.append(
                        {
                            "package": pkg,
                            "version": version,
                            "url": url,
                            "sha256": hashlib.sha256(response.content).hexdigest(),
                            "bytes": len(response.content),
                            "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        }
                    )
                    break
            else:
                manifest.append({"package": pkg, "version": version, "error": "not_found"})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(sum("sha256" in m for m in manifest), "of", len(manifest), "fetched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
