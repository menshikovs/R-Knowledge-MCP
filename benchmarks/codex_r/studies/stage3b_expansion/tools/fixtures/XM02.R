# Public sample fixture for XM02 (candidate-visible). Seed 2045 is NOT used by any hidden variant.
set.seed(2045, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
sites <- rep(c("north", "south", "west"), c(16L, 14L, 18L))
n <- length(sites)
arm <- unlist(lapply(c(16L, 14L, 18L), function(m) sample(rep(c("control", "active"), length.out = m))))
base <- round(rnorm(n, 50, 8), 2)
site_eff <- c(north = 0, south = 3.5, west = -2.0)[sites]
trt_eff <- c(north = 4.2, south = 4.0, west = 4.5)[sites] * (arm == "active")
out_val <- round(20 + 0.45 * base + site_eff + trt_eff + rnorm(n, 0, 2.2), 3)
post_adh <- round(pmin(1, pmax(0, 0.7 + 0.15 * (arm == "active") + 0.02 * (out_val - mean(out_val)) + rnorm(n, 0, 0.08))), 3)
post_adh[sample.int(n, 10L)] <- NA_real_
df <- data.frame(
  subject_id = sprintf("SUBJ-%03d", seq_len(n)),
  arm = arm,
  site = sites,
  baseline = base,
  post_adherence = post_adh,
  outcome = out_val,
  stringsAsFactors = FALSE
)
df$outcome[c(5L, 29L)] <- NA_real_
df <- df[sample.int(nrow(df)), ]
out_dir <- Sys.getenv("OUT_DIR", "/out")
write.csv(df, file.path(out_dir, "study.csv"), row.names = FALSE)

