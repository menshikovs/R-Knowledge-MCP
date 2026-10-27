euro <- utils::read.csv("/candidate/data/euro_amounts.csv", stringsAsFactors=FALSE, na.strings="")$raw
input <- c(euro, "nothing to parse", NA_character_)
check("numeric vector with preserved length", {
  out <- call_candidate("parse_euro_amount", input)
  is.numeric(value_of(out)) && length(value_of(out)) == length(input)
})
check("European decimal and grouping marks", {
  out <- value_of(call_candidate("parse_euro_amount", input))
  isTRUE(all.equal(out[1:3], c(1234.5, 2005.1, -12.75)))
})
check("invalid and missing input become NA", {
  out <- value_of(call_candidate("parse_euro_amount", input))
  all(is.na(out[4:6]))
})
check("input is not reordered or changed", {
  out <- call_candidate("parse_euro_amount", input)
  identical(out$args_after[[1L]], input)
})
check("quiet parsing", {
  out <- call_candidate("parse_euro_amount", input)
  length(out$warnings) == 0L
})
