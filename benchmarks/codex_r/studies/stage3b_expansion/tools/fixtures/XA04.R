# Public sample fixture for XA04 (candidate-visible). Seed 2029 is NOT used by any hidden variant.
set.seed(2029, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 12L
times <- c("baseline", "week4", "week8")
sigma <- matrix(c(1, 0.85, 0.2, 0.85, 1.2, 0.4, 0.2, 0.4, 3), 3)
z <- matrix(rnorm(n * 3), n, 3) %*% chol(sigma)
y <- sweep(z, 2, c(50, 52, 55), "+")
d <- data.frame(subject = rep(sprintf("S%02d", seq_len(n)), times = 3),
                time = rep(times, each = n), score = round(as.vector(y), 2))
d <- d[sample.int(nrow(d)), ]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "measurements.csv"), row.names = FALSE)
