# Public sample fixture for XR01 (candidate-visible). Seed 2040 is NOT used by any hidden variant.
set.seed(2040, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 36L
d <- data.frame(team = sample(c("red", "blue", "green"), n, replace = TRUE),
                player = sprintf("p%02d", seq_len(n)),
                points = sample(c(5:25, NA), n, replace = TRUE))
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "scores.csv"), row.names = FALSE, na = "")
