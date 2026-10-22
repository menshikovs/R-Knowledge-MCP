# R07: Safe SQL aggregation

Implement `revenue_by_region(con, from_date, to_date)` using a parameterized SQL query on the supplied SQLite connection. Tables: customers(id INTEGER, region TEXT), orders(id INTEGER, customer_id INTEGER, order_date TEXT ISO YYYY-MM-DD, amount REAL). Include orders from_date inclusive to to_date exclusive; use a LEFT JOIN, group missing/NULL regions as 'Unknown', treat NULL amount as zero, and include zero-revenue groups. Return region (character), revenue (double), orders (integer), sorted by region. Preserve the supplied connection and all database contents. Boundaries are untrusted strings, never SQL fragments.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: DBI, RSQLite.
Example input is in data/orders.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
