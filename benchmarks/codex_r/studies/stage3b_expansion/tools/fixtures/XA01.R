# Public sample fixture for XA01 (candidate-visible). Seed 2027 is NOT used by any hidden variant.
set.seed(2027, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
labels <- c("placebo", "low", "mid", "high")
n <- c(9L, 14L, 6L, 11L)
mu <- c(20, 22, 27, 21)
sd <- c(2, 3, 9, 1.5)
y <- unlist(Map(function(k, m, s) rnorm(k, m, s), n, mu, sd))
d <- data.frame(participant_id = sprintf("S%03d", sample.int(sum(n))),
                group = rep(labels, times = n), score = round(y, 2))
d <- d[sample.int(nrow(d)), ]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "experiment.csv"), row.names = FALSE)
