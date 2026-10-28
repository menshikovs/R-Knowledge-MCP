"""D01 arm comparison with an honest interval (exploratory; trials from different runs/configurations are pooled exactly as the dashboard would)."""
import random
import statistics
import sys

import duckdb

con = duckdb.connect(sys.argv[1], read_only=True)
rows = con.execute(
    "select mode, run_id, condition, configuration, scorer_version, passed, total, mcp_calls_observed from trials where task_id='D01' and status='scored' and total is not null order by started_at"
).fetchall()
for r in rows:
    print(r)
a = [p / t for m, _, _, _, _, p, t, _ in rows if m == "without-mcp"]
b = [p / t for m, _, _, _, _, p, t, _ in rows if m == "with-mcp"]
print("without n", len(a), "mean", round(statistics.mean(a), 3), "| with n", len(b), "mean", round(statistics.mean(b), 3))
rng = random.Random(1729)
diffs = []
for _ in range(20000):
    sa = [rng.choice(a) for _ in a]
    sb = [rng.choice(b) for _ in b]
    diffs.append(statistics.mean(sb) - statistics.mean(sa))
diffs.sort()
print("difference of means", round(statistics.mean(b) - statistics.mean(a), 3), "| bootstrap 95% interval", round(diffs[500], 3), "to", round(diffs[19500], 3))
fa = sum(1 for x in a if x == 1.0)
fb = sum(1 for x in b if x == 1.0)
print("fully correct: without", fa, "/", len(a), "| with", fb, "/", len(b))
used = [p / t for m, _, _, _, _, p, t, c in rows if m == "with-mcp" and (c or 0) > 0]
unused = [p / t for m, _, _, _, _, p, t, c in rows if m == "with-mcp" and not c]
print("with-MCP trials that used MCP:", len(used), "mean", round(statistics.mean(used), 3) if used else None, "| that did not:", len(unused), "mean", round(statistics.mean(unused), 3) if unused else None)
