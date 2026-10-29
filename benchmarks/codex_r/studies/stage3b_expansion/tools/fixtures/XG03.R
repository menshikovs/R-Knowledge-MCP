# Public sample fixture for XG03 (candidate-visible). Seed 2034 is NOT used by any hidden variant.
set.seed(2034, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
groups <- c("students", "workers", "retired")
regions <- c("coast", "inland", "mountain")
probs <- list(students = c(.5, .4, .1), workers = c(.3, .6, .1), retired = c(.2, .8, 0))
n <- c(40L, 55L, 25L)
d <- do.call(rbind, Map(function(g, k) {
  data.frame(group = g, region = sample(regions, k, replace = TRUE, prob = probs[[g]]),
             stringsAsFactors = FALSE)
}, groups, n))
d$respondent_id <- sprintf("R%03d", sample.int(nrow(d)))
d <- d[sample.int(nrow(d)), c("respondent_id", "group", "region")]
rownames(d) <- NULL
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "respondents.csv"), row.names = FALSE)
