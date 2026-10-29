"""Regenerate public task fixtures inside the sandboxed scorer image (no network, non-root).

    python -m benchmarks.codex_r.studies.stage3b_expansion.tools.make_fixtures XA03 [XA05 ...]

Each ``tools/fixtures/<ID>.R`` writes its CSV files to ``$OUT_DIR`` (mounted as the only writable
bind mount); the files are copied to ``tasks/<ID>/fixture/``. Fixture content is deterministic
(explicit RNG kinds, R 4.5.2) and a test regenerates it to prove the committed files match.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from benchmarks.codex_r.runner import bench

STAGE3B = Path(__file__).resolve().parents[1]
SCORER_IMAGE = "codex-r-benchmark:pilot"


def generate(task_id: str, image: str = SCORER_IMAGE) -> dict[str, bytes]:
    script = STAGE3B / "tools" / "fixtures" / f"{task_id}.R"
    if not script.is_file():
        raise FileNotFoundError(script)
    image_id = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="rkmcp-s3b-fixture-") as temp:
        out = Path(temp) / "out"
        out.mkdir()
        out.chmod(0o777)
        environment = {"HOME": "/tmp", "TZ": "UTC", "LC_ALL": "C.UTF-8", "OUT_DIR": "/out"}
        command = ["docker", "run", "--rm", "--name", "codex-r-score-" + uuid.uuid4().hex]
        command += ["--network", "none", "--read-only", "--cap-drop", "ALL"]
        command += ["--security-opt", "no-new-privileges", "--user", "65534:65534"]
        command += ["--tmpfs", "/tmp:rw,nosuid,size=128m,mode=1777"]
        for key, value in environment.items():
            command += ["--env", f"{key}={value}"]
        command += ["--mount", f"type=bind,source={script.parent},target=/src,readonly"]
        command += ["--mount", f"type=bind,source={out},target=/out"]
        command += [image_id, "Rscript", "--vanilla", f"/src/{task_id}.R"]
        result = bench.execute_container(command, timeout=300)
        if result.returncode:
            raise RuntimeError(f"fixture generator failed: {result.stderr.decode()[-800:]}")
        return {p.name: p.read_bytes().replace(b"\r\n", b"\n") for p in sorted(out.iterdir())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="+")
    parser.add_argument("--check", action="store_true", help="compare with committed files only")
    args = parser.parse_args(argv)
    status = 0
    for task_id in args.tasks:
        fresh = generate(task_id)
        target = STAGE3B / "tasks" / task_id / "fixture"
        for name, content in fresh.items():
            path = target / name
            if args.check:
                same = path.is_file() and path.read_bytes() == content
                print(f"{task_id}/{name}: {'identical' if same else 'DIFFERENT'}")
                status |= 0 if same else 1
            else:
                target.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                print(f"{task_id}/{name}: written ({len(content)} bytes)")
    return status


if __name__ == "__main__":
    sys.exit(main())
