# Public sample fixture for XV04 (candidate-visible). Seed 2039 is NOT used by any hidden variant.
set.seed(2039, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- c(control = 120L, treated = 60L)
d <- do.call(rbind, lapply(names(n), function(g) {
  data.frame(value = round(rnorm(n[[g]], mean = if (g == "control") 10 else 12, sd = 2), 3), group = g)
}))
d$value[sample.int(nrow(d), 4)] <- NA
d <- d[sample.int(nrow(d)), ]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "measurements.csv"), row.names = FALSE, na = "")
