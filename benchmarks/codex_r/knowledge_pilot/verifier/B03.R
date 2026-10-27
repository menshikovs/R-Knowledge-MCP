lines <- utils::read.csv("/candidate/data/invoice_lines.csv", stringsAsFactors=FALSE)
check("output columns and invoice order", {
  out <- value_of(call_candidate("invoice_totals", lines))
  identical(names(out), c("invoice_id", "line_count", "total")) &&
    identical(out$invoice_id, c("I-1", "I-2", "I-3"))
})
check("latest revision replaces earlier line", {
  out <- value_of(call_candidate("invoice_totals", lines))
  out$line_count[out$invoice_id == "I-1"] == 2L && out$total[out$invoice_id == "I-1"] == 24
})
check("latest cancellation removes a line", {
  out <- value_of(call_candidate("invoice_totals", lines))
  out$line_count[out$invoice_id == "I-2"] == 1L && out$total[out$invoice_id == "I-2"] == -14
})
check("zero quantity remains counted", {
  out <- value_of(call_candidate("invoice_totals", lines))
  out$line_count[out$invoice_id == "I-1"] == 2L
})
check("duplicate revision uses latest received record once", {
  out <- value_of(call_candidate("invoice_totals", lines))
  out$line_count[out$invoice_id == "I-3"] == 1L && out$total[out$invoice_id == "I-3"] == 8
})
