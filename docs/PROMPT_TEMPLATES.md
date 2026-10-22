# Prompt template catalog

Templates live as version-controlled data in
src/cran_knowledge_mcp/prompt_intelligence/templates.py. They are selected by
stable ID through list_r_prompt_templates and build_r_prompt; there is no
separate server or template-specific MCP tool. Package names and function
references below are candidate lookup inputs, not endorsements or claims that
the package/API is installed. At runtime, the existing CRAN provider checks
package metadata, version and exact Rd aliases. Unavailable packages and docs
remain explicit. Current docs are not substituted for requested historical
package versions.

| Template ID | Intent | Candidate packages | Function references looked up when package is verified |
| --- | --- | --- | --- |
| csv-import | Delimited-file import | readr, data.table, vroom | readr::read_delim, data.table::fread, vroom::vroom |
| csv-cleaning | CSV cleaning | dplyr, tidyr, janitor | janitor::clean_names, dplyr::mutate, dplyr::distinct |
| csv-validation | Data-quality checks | pointblank, validate | pointblank::create_agent, validate::validator |
| csv-analysis | CSV analysis | readr, dplyr, ggplot2 | readr::read_csv, dplyr::summarise, ggplot2::ggplot |
| csv-export | CSV writing | readr, data.table | readr::write_delim, data.table::fwrite |
| sql-query | Dialect-aware database query | DBI, dbplyr | DBI::dbGetQuery, DBI::dbBind, dbplyr::show_query |
| sql-database | Database connection and lifecycle | DBI, odbc | DBI::dbConnect, DBI::dbWithTransaction, odbc::odbc |
| sql-performance | Query-plan analysis | DBI, dbplyr, duckdb | dbplyr::explain, DBI::dbGetQuery |
| sql-schema | Schema review and design | DBI | DBI::dbListTables, DBI::dbListFields |
| csv-sql-pipeline | CSV-to-database ETL | readr, DBI, duckdb | readr::read_delim, DBI::dbWriteTable, DBI::dbWithTransaction |

When a database_dialect is supplied, the builder adds and verifies its driver:
postgresql selects RPostgres::Postgres, sqlite selects RSQLite::SQLite, duckdb
selects duckdb::duckdb, mysql/mariadb selects RMariaDB::MariaDB, and sql_server
selects odbc::odbc. The SQL database template does not generate driver code for
an unselected dialect. The pipeline may use DuckDB as one local analytical
option; it does not presume DuckDB is appropriate for every use case.

## Template behavior

CSV import asks the downstream assistant to inspect file metadata or a small
sanitized sample, then make delimiter, encoding, decimal mark, quoting,
escaping, header, missing values, column types, locale and date/time-zone
assumptions explicit. Type inference is provisional, not a substitute for a
verified schema. Large-file requests include a memory and chunk/streaming plan.

CSV cleaning and validation distinguish transformation from testing. Prompts
require explicit missing-value and duplicate rules, measurable expectations,
failed-row reporting and preserved raw input. Validation does not silently fix
or write data. The builder never assumes an unseen schema; it requests column
names/types or a small sanitized example rather than the whole dataset.

CSV analysis asks for schema and parsing assumptions before dplyr or ggplot2
work. Export asks for encoding, delimiter, quoting, locale, timezone, header,
missing-value representation and a safe project-relative path. When a
spreadsheet application will consume the output, prompts discuss formula
injection from untrusted cells and require an explicit neutralization policy.

SQL query and database templates require the dialect and schema, distinguish
identifiers from values, prefer parameterized values, and cover joins, NULL,
types, timestamps, pagination, result shape, transaction semantics and resource
cleanup as relevant. SQL optimization asks for a measured plan/workload and
does not presume that adding an index or switching to DuckDB is best. Schema
design uses only caller-supplied table/column facts and asks to inspect the
current schema before proposing changes.

The CSV-to-SQL template sequences schema inspection, validation, CSV/SQL type
mapping, table selection/creation, idempotent duplicate policy, bounded batch
loading where justified, transaction/rollback, error recording and row-count
and integrity checks. It does not run SQL or access a database.

SQL safety guidance includes least-privilege credentials from environment
configuration, read-only inspection by default when requested, and explicit
authorization, backup and rollback before DROP, TRUNCATE, unrestricted DELETE,
destructive migrations or bulk overwrite. Selecting read-write access is not
authorization for those destructive operations.

## Practical MCP request examples

These JSON argument objects are prompts to another assistant; no database or
dataset is read by this MCP server.

Large CSV import:

    {"request":"Import a large CSV into R","task_category":"csv_import","structured_context":{"csv_columns":["id","amount"],"column_types":{"id":"character","amount":"numeric"},"delimiter":";","encoding":"UTF-8","decimal_separator":",","has_header":true,"estimated_rows":2500000}}

Clean and validate:

    {"request":"Clean and validate a CSV dataset","task_category":"data_validation","structured_context":{"csv_columns":["id","status"],"column_types":{"id":"character","status":"character"},"missing_values":["","NA"]}}

Analyze with dplyr and ggplot2:

    {"request":"Analyze the CSV data with dplyr and ggplot2; compare monthly totals","task_category":"csv_analysis","packages":["dplyr","ggplot2"],"structured_context":{"csv_columns":["date","amount"],"column_types":{"date":"Date","amount":"numeric"},"timezone":"UTC"}}

Query PostgreSQL from R:

    {"request":"Query PostgreSQL from R with parameterized date filters","task_category":"database_query","structured_context":{"database_dialect":"postgresql","table_schema":{"table":"measurements","columns":[{"name":"sample_id","type":"text","nullable":false},{"name":"recorded_at","type":"timestamptz","nullable":false}],"primary_key":["sample_id"]},"read_only":true}}

Inspect a DuckDB analytical query:

    {"request":"Optimize a DuckDB analytical query and explain the plan","task_category":"sql_optimization","structured_context":{"database_dialect":"duckdb","estimated_rows":5000000,"performance_requirements":"Keep peak memory below 2 GiB"}}

Load CSV to SQLite:

    {"request":"Load this CSV into SQLite with transaction and row-count checks","task_category":"etl_pipeline","structured_context":{"database_dialect":"sqlite","table_schema":{"table":"records","columns":[{"name":"record_id","type":"TEXT","nullable":false}],"primary_key":["record_id"]},"use_transactions":true,"read_only":false}}

## API documentation basis

The function names are checked against package documentation at runtime. The
template list is deliberately not a hard-coded statement of current package
versions or API availability. Reviewed primary documentation includes
[readr delimited-file readers](https://readr.tidyverse.org/reference/read_csv.html),
[data.table fread](https://rdatatable.gitlab.io/data.table/reference/fread.html)
and [fwrite](https://rdatatable.gitlab.io/data.table/reference/fwrite.html),
[DBI parameter binding](https://dbi.r-dbi.org/reference/dbBind.html) and
[identifier quoting](https://dbi.r-dbi.org/reference/dbQuoteIdentifier.html),
[dbplyr query inspection](https://dbplyr.tidyverse.org/reference/),
[RSQLite driver docs](https://rsqlite.r-dbi.org/reference/SQLite.html),
[RPostgres driver docs](https://rpostgres.r-dbi.org/reference/),
[DuckDB R client](https://r.duckdb.org/reference/duckdb.html), and
[pointblank create_agent](https://posit-dev.github.io/pointblank/reference/create_agent.html).
