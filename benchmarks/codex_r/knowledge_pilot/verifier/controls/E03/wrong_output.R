convert_expression_set <- function(x) {
  as.matrix(SummarizedExperiment::makeSummarizedExperimentFromExpressionSet(x))
}
