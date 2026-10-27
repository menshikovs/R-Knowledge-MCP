ledger <- utils::read.csv("/candidate/data/ledger.csv", stringsAsFactors=FALSE, na.strings="NA")
check("output columns", {
  z <- call_candidate("ledger_summary", ledger, "2025-01-01", "2025-01-05")
  identical(names(value_of(z)), c("account", "transactions", "total", "first_posted", "last_posted"))
})
check("eligibility and inclusive date bounds", {
  z <- value_of(call_candidate("ledger_summary", ledger, "2025-01-01", "2025-01-05"))
  identical(z$account, c("A-2", "B-1")) && identical(z$transactions, c(2L, 2L))
})
check("finite signed totals", {
  z <- value_of(call_candidate("ledger_summary", ledger, "2025-01-01", "2025-01-05"))
  isTRUE(all.equal(z$total, c(8, 4.5)))
})
check("first and last retained dates", {
  z <- value_of(call_candidate("ledger_summary", ledger, "2025-01-01", "2025-01-05"))
  identical(z$first_posted, c("2025-01-01", "2025-01-02")) &&
    identical(z$last_posted, c("2025-01-03", "2025-01-05"))
})
check("typed empty result", {
  z <- value_of(call_candidate("ledger_summary", ledger, "2030-01-01", "2030-01-02"))
  nrow(z) == 0L && identical(names(z), c("account", "transactions", "total", "first_posted", "last_posted")) &&
    is.integer(z$transactions) && is.numeric(z$total) && is.character(z$account)
})
