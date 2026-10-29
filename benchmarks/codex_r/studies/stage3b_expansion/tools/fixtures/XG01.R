# Public sample fixture for XG01 (candidate-visible). Seed 2032 is NOT used by any hidden variant.
set.seed(2032, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
days <- as.Date("2025-06-02") + 0:27
observed <- sort(sample(days, 17))
rows <- lapply(observed, function(day) {
  k <- sample(1:3, 1)
  data.frame(day = format(day), score = round(rnorm(k, 52, 6), 1))
})
d <- do.call(rbind, rows)
d$score[sample.int(nrow(d), 4)] <- NA
d$reading_id <- sprintf("R%03d", sample.int(nrow(d)))
d <- d[sample.int(nrow(d)), c("reading_id", "day", "score")]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "readings.csv"), row.names = FALSE, na = "")
