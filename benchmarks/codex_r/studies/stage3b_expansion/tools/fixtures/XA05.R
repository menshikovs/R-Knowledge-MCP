# Public sample fixture for XA05 (candidate-visible). Seed 2030 is NOT used by any hidden variant.
set.seed(2030, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
labels <- c("control", "coaching", "tutoring")
n <- c(14L, 11L, 13L)
slope <- c(0.8, 0.8, 0.8)
shift <- c(0, 3, 5)
parts <- lapply(seq_along(labels), function(i) {
  b <- round(rnorm(n[i], 50, 10), 1)
  data.frame(treatment = labels[i], baseline = b,
             score = round(10 + shift[i] + slope[i] * b + rnorm(n[i], sd = 4), 1),
             stringsAsFactors = FALSE)
})
d <- do.call(rbind, parts)
d$participant_id <- sprintf("P%03d", sample.int(nrow(d)))
d <- d[sample.int(nrow(d)), c("participant_id", "treatment", "baseline", "score")]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "trial.csv"), row.names = FALSE)
