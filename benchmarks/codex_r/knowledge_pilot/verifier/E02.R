counts <- utils::read.csv("/candidate/data/counts.csv", row.names=1, check.names=FALSE)
samples <- utils::read.csv("/candidate/data/samples.csv", row.names=1)
check("workflow_returns_a_result", {
  x <- value_of(call_candidate("run_rnaseq", counts, samples))
  is.list(x) && is.data.frame(x$results) && inherits(x$dds, "DESeqDataSet")
})
check("result_has_requested_columns", {
  x <- value_of(call_candidate("run_rnaseq", counts, samples))
  all(c("gene", "log2FoldChange", "pvalue", "padj") %in% names(x$results))
})
check("all_genes_present", {
  x <- value_of(call_candidate("run_rnaseq", counts, samples))
  nrow(x$results) == nrow(counts) && setequal(x$results$gene, rownames(counts))
})
check("count_container_and_samples", {
  x <- value_of(call_candidate("run_rnaseq", counts, samples))
  inherits(x$dds, "DESeqDataSet") && ncol(x$dds) == ncol(counts) &&
    nrow(x$dds) == nrow(counts)
})
check("reference_level_and_sign", {
  x <- value_of(call_candidate("run_rnaseq", counts, samples))
  x$results$log2FoldChange[x$results$gene == "gene_1"] > 0 &&
    x$results$log2FoldChange[x$results$gene == "gene_11"] < 0
})
