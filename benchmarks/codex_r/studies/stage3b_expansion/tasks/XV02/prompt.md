# XV02: The price in force on the order date

An online shop keeps a price history. A sample is in `data/orders.csv` (columns `order_id`, `sku`,
`order_date`) and `data/prices.csv` (columns `sku`, `price_date`, `price`; a row means the product
`sku` had that `price` **starting on** `price_date` until its next price change). The scripts run
under the package versions recorded in `renv.lock` and **must run without any warning or error**
there; a many-to-many join notice is a failure.

Write `solution.R` defining `price_in_force(orders, prices)`. Both arguments are data frames with
the columns above; the date columns are of class `Date`. Use only packages installed in the
supplied environment; do not install anything.

## Return value

A plain data frame with exactly the columns `order_id`, `sku`, `order_date`, `price_date`,
`price`, with **one row per row of `orders`, in the order of `orders`**.

- `price` and `price_date` are those of the price row for the same `sku` with the **latest
  `price_date` that is on or before `order_date`**. A price that starts on the order date applies.
- If the product has no price on or before the order date (or is not in `prices`), or the
  `order_date` is missing, both are `NA` (the row is kept).
- A given `sku` never has two rows with the same `price_date`.

## Rules

- Do not use information from later price changes (no leakage of future prices).
- Do not modify `orders` or `prices`.

The file will be sourced into a fresh R session and `price_in_force` called on data frames you have
not seen.
