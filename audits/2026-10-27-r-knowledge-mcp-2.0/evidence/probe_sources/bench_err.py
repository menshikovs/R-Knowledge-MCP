import sys

import duckdb

con = duckdb.connect(sys.argv[1], read_only=True)
for r in con.execute("select run_id, task_id, mode, status, substr(primary_error_json,1,160) from trials where status in ('error','interrupted') order by 1").fetchall():
    print(r)
print(con.execute("select count(*) from trials where mode='with-mcp' and status='scored' and mcp_calls_observed>0 and task_id in ('D01','D02')").fetchone())
print(con.execute("select configuration, instructions, count(*) from trials group by 1,2 order by 3 desc").fetchall())
print(con.execute("select condition, count(*) from trials group by 1").fetchall())
