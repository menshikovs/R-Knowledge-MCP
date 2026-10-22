"""Probe the actual candidate R container; not proof of an external Codex session."""

import argparse
import json
import tempfile
import uuid
from pathlib import Path

from bench import docker_command, execute_container, prepare


def probe(image):
    with tempfile.TemporaryDirectory(prefix="r-candidate-boundary-") as temp:
        work = Path(temp) / "candidate"
        exported = prepare("R01", work)
        command = docker_command(image, work)
        checks = """
checks <- list(
  oracle_absent = !file.exists("/oracle"),
  repository_absent = !file.exists("/repo"),
  docker_socket_absent = !file.exists("/var/run/docker.sock"),
  only_public_files = identical(sort(list.files("/candidate")),
                               sort(c("TASK.md","renv.lock","data")))
)
stopifnot(all(unlist(checks)))
cat(jsonlite::toJSON(checks,auto_unbox=TRUE))
"""
        command = [
            *command[:-2],
            "--name",
            "codex-r-score-" + uuid.uuid4().hex,
            image,
            "Rscript",
            "--vanilla",
            "-e",
            checks,
        ]
        result = execute_container(command, timeout=30)
        if result.returncode != 0:
            raise RuntimeError("Actual candidate filesystem probe failed")
        return {
            "kind": "candidate_R_container_only",
            "agent_session_isolation_verified": False,
            "image": image,
            "candidate_mount_targets": ["/candidate"],
            "network": "none",
            "read_only_root": True,
            "filesystem_checks": json.loads(result.stdout),
            "public_export": exported,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(probe(args.image), indent=2) + "\n", encoding="utf-8")
