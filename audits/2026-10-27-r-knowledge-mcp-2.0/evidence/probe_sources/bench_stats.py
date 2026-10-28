"""Descriptive + paired statistics from the local (untracked) benchmark DB. Exploratory only."""
import collections
import math
import sys

import duckdb

con = duckdb.connect(sys.argv[1], read_only=True)
q = lambda s: con.execute(s).fetchall()  # noqa: E731

print("trials:", q("select count(*), count(distinct run_id), count(distinct task_id) from trials"))
print("by mode/status:", q("select mode, status, count(*) from trials group by 1,2 order by 1,2"))
print("model/effort:", q("select model, effort, count(*) from trials group by 1,2"))
print("usage_status:", q("select usage_status, count(*) from trials group by 1"))
print("cost_status:", q("select cost_status, count(*) from trials group by 1"))
print("scorer_version:", q("select scorer_version, count(*) from trials group by 1"))
print("trials with mcp_calls_observed>0 among with-mcp scored:", q("select count(*) filter (where mcp_calls_observed>0), count(*) from trials where mode='with-mcp' and status='scored'"))

rows = q("""select task_id, mode, run_id, passed, total, mcp_calls_observed from trials where status='scored' and total>0""")
by = collections.defaultdict(lambda: {"without-mcp": [], "with-mcp": []})
for task, mode, run, passed, total, calls in rows:
    by[task][mode].append((passed / total, calls or 0, run))
print("\nper-task scored means (fraction of checks), n per arm:")
diffs = []
for task in sorted(by):
    a, b = by[task]["without-mcp"], by[task]["with-mcp"]
    if a and b:
        ma, mb = sum(x[0] for x in a) / len(a), sum(x[0] for x in b) / len(b)
        used = sum(1 for x in b if x[1] > 0)
        print(f"  {task}: without n={len(a)} mean={ma:.2f} | with n={len(b)} mean={mb:.2f} (trials with >=1 MCP call: {used}/{len(b)})")
        diffs.append((task, mb - ma, len(a), len(b)))
nz = [d for d in diffs if d[1] != 0]
print("\ntasks with both arms:", len(diffs), "| tasks with any difference:", len(nz), [(t, round(d, 2)) for t, d, _, _ in nz])
# exact sign test on non-zero differences
pos = sum(1 for _, d, _, _ in nz if d > 0)
n = len(nz)
if n:
    p = sum(math.comb(n, k) for k in range(pos, n + 1)) / 2 ** n
    print(f"sign test (one-sided, ties dropped): +{pos}/{n}, p={p:.3f}")
# repetition structure
print("\nmax repetitions per (task,mode):", q("select max(c) from (select task_id, mode, count(*) c from trials where status='scored' group by 1,2)"))
print("task/mode cells with n=1:", q("select count(*) from (select task_id, mode, count(*) c from trials where status='scored' group by 1,2) where c=1"), "of", q("select count(*) from (select task_id, mode, count(*) c from trials where status='scored' group by 1,2)"))
# within-condition replication on the same task/mode (variance evidence)
rep = q("""select task_id, mode, count(*), min(passed*1.0/total), max(passed*1.0/total) from trials where status='scored' and total>0 group by 1,2 having count(*)>1 order by 1,2""")
print("\nreplicated cells (n, min, max fraction):")
for r in rep:
    print("  ", r)
