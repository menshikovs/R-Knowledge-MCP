data(sample.ExpressionSet, package="Biobase")
check("result_class", {
  x <- value_of(call_candidate("convert_expression_set", sample.ExpressionSet))
  inherits(x, "RangedSummarizedExperiment")
})
check("assay_values_preserved", {
  x <- value_of(call_candidate("convert_expression_set", sample.ExpressionSet))
  identical(as.numeric(SummarizedExperiment::assay(x)), as.numeric(Biobase::exprs(sample.ExpressionSet)))
})
check("feature_names_preserved", {
  x <- value_of(call_candidate("convert_expression_set", sample.ExpressionSet))
  identical(rownames(x), Biobase::featureNames(sample.ExpressionSet))
})
check("phenotype_columns_preserved", {
  x <- value_of(call_candidate("convert_expression_set", sample.ExpressionSet))
  identical(names(SummarizedExperiment::colData(x)), names(Biobase::pData(sample.ExpressionSet)))
})
