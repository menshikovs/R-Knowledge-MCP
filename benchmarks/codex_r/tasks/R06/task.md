# R06: Parameterized account lookup

Implement `lookup_accounts(db_path, owner, min_balance)` in solution.R. Open your own SQLite connection and always disconnect it on success or failure. Table accounts has id INTEGER, owner TEXT, balance REAL. Use bound query parameters to select exact owner equality and balance >= min_balance, excluding NULL balances; return id (integer), owner (character), balance (double), ordered by id. Treat SQL-looking owner strings as data. Never change database contents. Validate min_balance is one finite number.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: DBI, RSQLite.
Example input is in data/accounts.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
