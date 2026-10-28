"""SEC-001 before/after: the audited quadratic dcf() (verbatim algorithm) vs the current linear one.

Run:  python -I bench_dcf.py   (from an environment where cran_knowledge_mcp is importable)
"""

import statistics
import time
import tracemalloc

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.parsers import dcf as new_dcf


def old_dcf(text):  # the implementation at audited commit 4d2266c, unchanged
    records, record, key = [], {}, ""
    for line in text.splitlines() + [""]:
        if not line.strip():
            if record:
                records.append(record)
            record, key = {}, ""
        elif line[0].isspace() and key:
            record[key] += " " + line.strip()
        elif ":" in line:
            key, value = line.split(":", 1)
            if key in record:
                raise KnowledgeError("invalid_source", "Duplicate DCF field")
            record[key] = value.strip()
        else:
            raise KnowledgeError("invalid_source", "Malformed CRAN DCF data")
    return records


def measure(fn, text, repeats):
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn(text)
        times.append(time.perf_counter() - started)
    tracemalloc.start()
    fn(text)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return statistics.median(times), peak


print(f"{'continuation lines':>20} {'input MB':>9} | {'old s':>8} {'old peak MB':>11} | {'new s':>8} {'new peak MB':>11} | speed-up")
for lines in (20_000, 80_000, 350_000, 698_000):
    text = "Package: x\nDescription: start\n" + " y\n" * lines
    new_s, new_peak = measure(new_dcf, text, 5)
    old_s, old_peak = measure(old_dcf, text, 1 if lines >= 350_000 else 3)
    assert new_dcf(text) == old_dcf(text) if lines <= 80_000 else True
    print(
        f"{lines:>20} {len(text) / 1e6:>9.2f} | {old_s:>8.3f} {old_peak / 1e6:>11.1f} | "
        f"{new_s:>8.3f} {new_peak / 1e6:>11.1f} | {old_s / new_s:>7.0f}x"
    )
text = "Package: x\nDescription: start\n" + " y\n" * 698_000
assert new_dcf(text)[0]["Description"] == "start" + " y" * 698_000
print("new implementation result for 698 000 lines verified")
