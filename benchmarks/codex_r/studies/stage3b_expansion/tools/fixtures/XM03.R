# Public sample fixture for XM03 (candidate-visible). Seed 2046 is NOT used by any hidden variant.
set.seed(2046, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 36L
cohorts <- rep(c("cardio", "neuro", "onco"), c(12L, 12L, 12L))
df <- data.frame(
  record_id = sprintf("REC-%03d", seq_len(n)),
  cohort = cohorts,
  score = round(runif(n, 10, 95), 2),
  weight = round(runif(n, 0.5, 3.5), 2),
  stringsAsFactors = FALSE
)
df <- df[sample.int(nrow(df)), ]
out_dir <- Sys.getenv("OUT_DIR", "/out")
write.csv(df, file.path(out_dir, "cohorts.csv"), row.names = FALSE)

