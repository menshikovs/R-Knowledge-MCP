"""Drive the real termr terminal driver through a pseudo-terminal (no mocks of termr).

`Session` starts tests/pty_entry.R (the real launcher UI + the fake runner) on a PTY,
sends key sequences and collects the bytes termr writes. Used by the pytest wrapper and
by hand: python3 pty_drive.py ctrlc
"""

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

ENTRY = Path(__file__).with_name("pty_entry.R")
KEYS = {
    "f5": b"\x1b[15~",
    "f10": b"\x1b[21~",
    "ctrl+x": b"\x18",
    "ctrl+c": b"\x03",
    "tab": b"\t",
    "enter": b"\r",
    "escape": b"\x1b",
}
ANSI = re.compile(r"\x1b(?:\[[0-9;?<>]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-B])")


class Session:
    def __init__(self, mode="ok", rows=24, cols=80, extra_env=None, entry=ENTRY, unset=()):
        env = dict(os.environ, TERM="xterm-256color", FAKE_MODE=mode, **(extra_env or {}))
        for name in unset:
            env.pop(name, None)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe("Rscript", ["Rscript", str(entry)], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.text = ""

    def read(self, seconds=1.0, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.text += ANSI.sub("", chunk.decode("utf8", "replace"))
            if until and until in self.text:
                return True
        return until is None or until in self.text

    def send(self, *names, pause=0.3):
        for name in names:
            os.write(self.fd, KEYS.get(name, name.encode() if isinstance(name, str) else name))
            self.read(pause)

    def children(self):
        out = subprocess.run(
            ["pgrep", "-P", str(self.pid)], capture_output=True, text=True, check=False
        ).stdout.split()
        return [int(pid) for pid in out]

    def runner_pids(self):
        return [pid for pid in self.children() if "fake_runner" in _cmdline(pid)]

    def alive(self):
        return Path(f"/proc/{self.pid}").exists() and not _zombie(self.pid)

    def close(self):
        for pid in [self.pid, *self.runner_pids()]:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.waitpid(self.pid, 0)
        except OSError:
            pass
        os.close(self.fd)


def _cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return ""


def _zombie(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[-1].startswith("Z")
    except OSError:
        return True


def pid_alive(pid):
    return Path(f"/proc/{pid}").exists() and not _zombie(pid)


if __name__ == "__main__":
    scenario = sys.argv[1]
    session = Session("sigint")
    try:
        print("READY:", session.read(8, "READY"))
        session.send("f5")
        print("RUNNING:", session.read(4, "RUNNING"))
        runner = session.runner_pids()
        print("runner pids:", runner)
        if scenario == "ctrlc":
            session.send("ctrl+c")
            print("dialog:", "experiment is running" in session.text.lower())
            session.send("tab")
            session.send("enter", pause=0.5)
            print("STOPPING:", session.read(3, "STOPPING"))
            time.sleep(3)
            session.read(1)
            print(
                "launcher alive:", session.alive(), "runner alive:", [pid_alive(p) for p in runner]
            )
        elif scenario in {"sigterm", "sighup", "sigkill"}:
            sig = {"sigterm": signal.SIGTERM, "sighup": signal.SIGHUP, "sigkill": signal.SIGKILL}[
                scenario
            ]
            os.kill(session.pid, sig)
            os.waitpid(session.pid, 0)  # reap it as an interactive shell would
            time.sleep(5)
            print(
                "launcher alive:", session.alive(), "runner alive:", [pid_alive(p) for p in runner]
            )
    finally:
        session.close()
