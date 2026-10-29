# Public sample fixture for XA06 (candidate-visible). Seed 2031 is NOT used by any hidden variant.
set.seed(2031, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 30L
visits <- c("month0", "month3", "month6")
id <- sprintf("P%02d", seq_len(n))
treatment <- rep(c("usual_care", "program"), each = n / 2)
u <- rnorm(n, sd = 3)
trend <- list(usual_care = c(0, 0.5, 1), program = c(0, 2.5, 5))
rows <- lapply(seq_len(n), function(i) {
  keep <- if (runif(1) < 0.25) sort(sample(3, 2)) else 1:3
  data.frame(id = id[i], treatment = treatment[i], time = visits[keep],
             score = round(60 + u[i] + trend[[treatment[i]]][keep] + rnorm(length(keep), sd = 2), 2),
             stringsAsFactors = FALSE)
})
d <- do.call(rbind, rows)
d <- d[sample.int(nrow(d)), ]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "visits.csv"), row.names = FALSE)
