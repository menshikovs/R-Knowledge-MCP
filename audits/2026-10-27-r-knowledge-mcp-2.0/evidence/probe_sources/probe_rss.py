"""Peak working set (Windows) of source_files for hostile archives, each parsed in a fresh process from a prebuilt file."""
import gzip
import io
import os
import subprocess
import sys
import tarfile
import tempfile

NL = chr(10)
CHILD = r'''
import ctypes, ctypes.wintypes as wt, sys
from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.parsers import source_files
class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
def peak():
    p = PMC(); p.cb = ctypes.sizeof(p)
    k = ctypes.WinDLL("kernel32"); k.GetCurrentProcess.restype = wt.HANDLE
    f = ctypes.WinDLL("psapi").GetProcessMemoryInfo; f.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]; f.restype = wt.BOOL
    assert f(k.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return p.PeakWorkingSetSize / 1e6
body = open(sys.argv[1], "rb").read(); size = int(sys.argv[2]); before = peak()
try:
    source_files(body, "Ex"); out = "ok"
except KnowledgeError as e:
    out = e.code
print(f"expanded payload {size/1e6:6.1f} MB (compressed {len(body)/1e3:6.0f} KB) -> {out:17} peak working set: before parse {before:6.1f} MB, after {peak():6.1f} MB")
'''


def make(size):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, payload in (("Ex/DESCRIPTION", b"Package: Ex" + NL.encode() + b"Version: 1.0" + NL.encode()), ("Ex/man/z.Rd", bytes(size))):
            i = tarfile.TarInfo(name)
            i.size = len(payload)
            t.addfile(i, io.BytesIO(payload))
    return gzip.compress(buf.getvalue(), 1)


for size in (1000, 100 << 20, 127 << 20):
    path = os.path.join(tempfile.mkdtemp(), "a.tgz")
    with open(path, "wb") as fh:
        fh.write(make(size))
    print(subprocess.run([sys.executable, "-I", "-c", CHILD, path, str(size)], capture_output=True, text=True).stdout.strip())
