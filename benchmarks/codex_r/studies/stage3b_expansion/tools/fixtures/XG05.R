# Public sample fixture for XG05 (candidate-visible). Seed 2036 is NOT used by any hidden variant.
set.seed(2036, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 8L
weeks <- 1:5
u <- rnorm(n, sd = 3)
d <- do.call(rbind, lapply(seq_len(n), function(i) {
  data.frame(subject = sprintf("P%02d", i), week = weeks,
             score = round(40 + u[i] + 2.2 * weeks + rnorm(length(weeks), sd = 2), 1))
}))
d$score[sample.int(nrow(d), 5)] <- NA
d <- d[sample.int(nrow(d)), ]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "trajectories.csv"), row.names = FALSE, na = "")
