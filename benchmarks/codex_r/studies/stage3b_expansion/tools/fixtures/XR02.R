# Public sample fixture for XR02 (candidate-visible). Seed 2041 is NOT used by any hidden variant.
set.seed(2041, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 24L
before <- round(rnorm(n, 120, 12), 1)
after <- round(before - 4 + rnorm(n, 0, 6), 1)
d <- data.frame(id = sprintf("c%02d", seq_len(n)), before = before, after = after)
d$before[3] <- NA
d$after[11] <- NA
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "clinic.csv"), row.names = FALSE, na = "")
