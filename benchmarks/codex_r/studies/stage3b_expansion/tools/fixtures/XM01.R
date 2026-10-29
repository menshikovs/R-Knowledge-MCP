# Public sample fixture for XM01 (candidate-visible). Seed 2044 is NOT used by any hidden variant.
set.seed(2044, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
g <- 40L
samples <- sprintf("S%02d", 1:12)
cond <- rep(c("control", "treated"), each = 6)
batch <- rep(rep(c("b1", "b2", "b3"), each = 2), 2)
base <- exp(rnorm(g, 5.5, 1))
lfc <- c(rep(1.5, 5), rep(-1.5, 3), rep(0, g - 8))
beff <- matrix(rnorm(g * 3, 0, 0.6), g, 3)
mu <- sapply(seq_along(samples), function(j) base * 2^(lfc * (cond[j] == "treated") + beff[, as.integer(sub("b", "", batch[j]))]))
cnt <- matrix(rnbinom(length(mu), mu = mu, size = 15), nrow = g,
              dimnames = list(sprintf("g%03d", seq_len(g)), samples))
out <- Sys.getenv("OUT_DIR", "/out")
write.csv(cnt, file.path(out, "counts.csv"))
cd <- data.frame(sample = samples, condition = cond, batch = batch)
cd <- cd[sample.int(nrow(cd)), ]
write.csv(cd, file.path(out, "coldata.csv"), row.names = FALSE)
