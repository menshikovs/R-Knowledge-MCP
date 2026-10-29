# Public sample fixture for XA02 (candidate-visible). Seed 2028 is NOT used by any hidden variant.
set.seed(2028, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
tl <- c("standard", "enhanced", "intensive")
sl <- c("urban", "rural", "coastal")
reps <- 6L
grid <- expand.grid(treatment = tl, site = sl, stringsAsFactors = FALSE)
effect <- matrix(c(0, 2, 4, 3, 0, -2, 1, 5, 0), nrow = 3, dimnames = list(tl, sl))
parts <- lapply(seq_len(nrow(grid)), function(k) {
  mu <- 40 + effect[grid$treatment[k], grid$site[k]]
  data.frame(treatment = grid$treatment[k], site = grid$site[k],
             score = round(mu + rnorm(reps, sd = 2.5), 2), stringsAsFactors = FALSE)
})
d <- do.call(rbind, parts)
d$participant_id <- sprintf("P%03d", sample.int(nrow(d)))
d <- d[sample.int(nrow(d)), c("participant_id", "treatment", "site", "score")]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "experiment.csv"), row.names = FALSE)
