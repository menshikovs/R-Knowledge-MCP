# Public sample fixture for XR04 (candidate-visible). Seed 2043 is NOT used by any hidden variant.
set.seed(2043, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
ids <- 1:8
keys <- c("height", "weight", "bp sys")
d <- expand.grid(id = ids, key = keys, stringsAsFactors = FALSE)
d <- d[sample.int(nrow(d), 20), ]
d <- rbind(d, d[sample.int(nrow(d), 5), ])
d$value <- round(rnorm(nrow(d), 70, 10), 1)
d$value[sample.int(nrow(d), 3)] <- NA
d <- d[sample.int(nrow(d)), ]
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "long.csv"), row.names = FALSE, na = "")
