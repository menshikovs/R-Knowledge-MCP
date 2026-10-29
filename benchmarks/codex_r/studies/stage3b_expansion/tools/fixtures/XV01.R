# Public sample fixture for XV01 (candidate-visible). Seed 2037 is NOT used by any hidden variant.
set.seed(2037, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
n <- 60L
region <- sample(c("north", "south", "east", "west"), n, replace = TRUE, prob = c(.4, .3, .2, .1))
amount <- round(rlnorm(n, 4, .6), 2)
amount[sample.int(n, 5)] <- NA
write.csv(data.frame(region = region, amount = amount), file.path(Sys.getenv("OUT_DIR", "/out"), "sales.csv"),
          row.names = FALSE, na = "")
