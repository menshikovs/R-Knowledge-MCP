# XV05: Parsing an event log held in a string

A service writes events as CSV. A sample file is `data/events.csv` (columns `ts`, `user`, `amount`,
`status`). Your code receives the **file contents as a single string** (for example the body of an
HTTP response), not a file path. The scripts run under the package versions recorded in
`renv.lock` and **must run without any warning or error** there.

Write `solution.R` defining `parse_events(text)`. `text` is a character string holding a CSV with a
header row. Use only packages installed in the supplied environment; do not install anything.

## Return value

A list with exactly these elements:

| element | content |
| --- | --- |
| `data` | data frame with columns `ts`, `user`, `amount`, `status`, in that order, one row per data row of `text`, in file order |
| `n_problems` | integer: the number of values that were present but could not be parsed (see below) |

Column types in `data`:

- `ts`: `POSIXct` in UTC, parsed from `YYYY-MM-DD HH:MM:SS`. An impossible date or other text
  becomes `NA` and counts as a problem.
- `user`: **character**, exactly as written (identifiers such as `007` keep their leading zeros).
- `amount`: numeric (double). Text that is not a plain number (for example `n/a` or `1,234.5`)
  becomes `NA` and counts as a problem.
- `status`: character.

An empty field or the text `NA` is a missing value (`NA`) in any column and is **not** a problem.
Quoted fields may contain commas. A text with a header and no data rows gives a zero-row data
frame with the same columns and types.

## Rules

- Parse `text` only; do not read files or the network. Do not modify global options.

The file will be sourced into a fresh R session and `parse_events` called on strings you have not
seen.
