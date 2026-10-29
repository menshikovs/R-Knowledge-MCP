# Public sample fixture for XA03 (candidate-visible). Seed 2026 is NOT used by any hidden variant.
# Run via tools/make_fixtures.py (sandboxed scorer image, no network).
set.seed(2026, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
tl <- c("control", "low", "high")
pl <- c("north", "south")
sizes <- c(5L, 8L, 6L, 10L, 4L, 7L)   # control/low/high within north, then within south
grid <- expand.grid(treatment = tl, program = pl, stringsAsFactors = FALSE)
parts <- lapply(seq_len(nrow(grid)), function(k) {
  i <- match(grid$treatment[k], tl)
  j <- match(grid$program[k], pl)
  mu <- 70 + c(0, 4, -2)[i] + c(0, 5)[j] + if (i == 3L && j == 2L) -6 else 0
  data.frame(treatment = grid$treatment[k], program = grid$program[k],
             score = round(mu + rnorm(sizes[k], sd = 4), 2), stringsAsFactors = FALSE)
})
d <- do.call(rbind, parts)
d$participant_id <- sprintf("P%03d", sample.int(nrow(d)))
d <- d[sample.int(nrow(d)), c("participant_id", "treatment", "program", "score")]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "experiment.csv"), row.names = FALSE)
