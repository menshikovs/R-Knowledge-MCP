# Public sample fixture for XV03 (candidate-visible): illustrative constructions and their kinds.
ex <- data.frame(
  construction = c("NULL", "sum", "function(x) x", "tibble::tibble(a = 1:2)", "data.frame(a = 1:2)",
                   "matrix(1:6, 2)", "array(1:8, c(2, 2, 2))", "factor(c('a', 'b'))",
                   "list(1, 'a')", "c(1.5, 2)", "Sys.Date()", "new.env()"),
  kind = c("NULL", "function", "function", "tibble", "data.frame", "matrix", "array", "factor",
           "list", "vector", "vector", "other")
)
write.csv(ex, file.path(Sys.getenv("OUT_DIR", "/out"), "examples.csv"), row.names = FALSE)
