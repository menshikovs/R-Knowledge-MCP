"""Hostile-archive behaviour of parsers.source_files: traversal names, links, devices, bombs, duplicates, oversize. Memory only; nothing is written to disk."""
import gzip
import io
import tarfile
import time
import tracemalloc

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.parsers import source_files

DESC = b"Package: Ex\nVersion: 1.0\n"


def build(members, compresslevel=9):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, kind, payload in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(payload)
                t.addfile(info, io.BytesIO(payload))
            elif kind == "sym":
                info.type = tarfile.SYMTYPE
                info.linkname = payload
                t.addfile(info)
            elif kind == "hard":
                info.type = tarfile.LNKTYPE
                info.linkname = payload
                t.addfile(info)
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
                t.addfile(info)
            elif kind == "dev":
                info.type = tarfile.CHRTYPE
                t.addfile(info)
    return gzip.compress(buf.getvalue(), compresslevel)


def run(label, body):
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        files = source_files(body, "Ex")
        out = "ok members=" + ",".join(sorted(files))
    except KnowledgeError as exc:
        out = f"KnowledgeError:{exc.code}"
    except Exception as exc:  # noqa: BLE001
        out = f"UNHANDLED {type(exc).__name__}: {exc}"
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    print(f"{label:58} {(time.perf_counter() - t0) * 1000:8.0f} ms  peak {peak / 1e6:7.1f} MB  {out}")


base = [("Ex/DESCRIPTION", "file", DESC)]
run("traversal names (../, absolute, backslash)", build(base + [("../evil/man/x.Rd", "file", b"x"), ("/abs/Ex/man/y.Rd", "file", b"x"), ("Ex/man/..\\z.Rd", "file", b"x"), ("Ex/man/a/b.Rd", "file", b"x")]))
run("symlink and hardlink named like Rd files", build(base + [("Ex/man/l.Rd", "sym", "/etc/passwd"), ("Ex/man/h.Rd", "hard", "Ex/DESCRIPTION"), ("Ex/NAMESPACE", "sym", "../../secret")]))
run("fifo / char device members", build(base + [("Ex/man/f.Rd", "fifo", None), ("Ex/man/c.Rd", "dev", None)]))
run("duplicate DESCRIPTION", build(base + [("Ex/DESCRIPTION", "file", DESC)]))
run("Rd member of 2 MiB + 1 byte", build(base + [("Ex/man/big.Rd", "file", b"a" * ((2 << 20) + 1))]))
run("17 x 1.5 MiB Rd (> 16 MiB total)", build(base + [(f"Ex/man/b{i}.Rd", "file", b"a" * (3 << 19)) for i in range(17)]))
run("20 001 tiny members", build(base + [(f"Ex/man/m{i}.Rd", "file", b"") for i in range(20001)], 1))
run("gzip bomb: 100 MiB of zeros in one member", build(base + [("Ex/man/z.Rd", "file", bytes(100 << 20))]))
run("gzip bomb: 200 MiB of zeros (over the 128 MiB cap)", build(base + [("Ex/man/z.Rd", "file", bytes(200 << 20))], 1))
