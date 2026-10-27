measurements <- utils::read.csv("/candidate/data/measurements.csv", stringsAsFactors=FALSE, na.strings="NA")
check("one row per sample in input order", {
  out <- value_of(call_candidate("measurements_wide", measurements))
  identical(out$sample, c("s1", "s2", "s3")) && nrow(out) == 3L
})
check("duplicate cell values aggregate", {
  out <- value_of(call_candidate("measurements_wide", measurements))
  out$A[[1L]] == 3
})
check("observed all-missing cell stays missing", {
  out <- value_of(call_candidate("measurements_wide", measurements))
  is.na(out$B[[1L]]) && is.na(out$A[[2L]])
})
check("only absent combinations receive zero", {
  out <- value_of(call_candidate("measurements_wide", measurements))
  out$C[[1L]] == 0 && out$B[[2L]] == 0 && out$A[[3L]] == 0
})
check("analyte columns are alphabetical and numeric", {
  out <- value_of(call_candidate("measurements_wide", measurements))
  identical(names(out), c("sample", "A", "B", "C")) &&
    all(vapply(out[c("A", "B", "C")], is.numeric, logical(1L)))
})
