# Public sample fixture for XG04 (candidate-visible). Seed 2035 is NOT used by any hidden variant.
set.seed(2035, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 90L
x <- round(runif(n, -2, 3), 3)
y <- round(1 + 1.2 * x + 0.9 * x^2 + rnorm(n, sd = 0.8), 3)
d <- data.frame(sample_id = sprintf("S%03d", seq_len(n)), x = x, y = y)
d$y[c(7, 40)] <- NA
d <- d[sample.int(nrow(d)), ]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "measurements.csv"), row.names = FALSE, na = "")
