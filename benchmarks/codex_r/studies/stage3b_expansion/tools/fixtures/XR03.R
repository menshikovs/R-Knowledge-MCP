# Public sample fixture for XR03 (candidate-visible). Seed 2042 is NOT used by any hidden variant.
set.seed(2042, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
v <- round(cumsum(rnorm(40, 0.2, 1)) + 50, 2)
v[c(9, 10, 27)] <- NA
write.csv(data.frame(value = v), file.path(Sys.getenv("OUT_DIR", "/out"), "series.csv"), row.names = FALSE, na = "")
