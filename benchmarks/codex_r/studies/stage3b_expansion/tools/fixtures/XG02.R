# Public sample fixture for XG02 (candidate-visible). Seed 2033 is NOT used by any hidden variant.
set.seed(2033, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
groups <- c("north", "south", "east", "west", "islands")
n <- c(9L, 12L, 8L, 11L, 5L)
d <- do.call(rbind, Map(function(g, k, m) {
  data.frame(group = g, y = round(rnorm(k, m, 3), 2), stringsAsFactors = FALSE)
}, groups, n, c(20, 24, 18, 22, 15)))
d$y[sample.int(nrow(d), 6)] <- NA
d$y[d$group == "islands"] <- NA
d$participant_id <- sprintf("P%03d", sample.int(nrow(d)))
d <- d[sample.int(nrow(d)), c("participant_id", "group", "y")]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "outcomes.csv"), row.names = FALSE, na = "")
