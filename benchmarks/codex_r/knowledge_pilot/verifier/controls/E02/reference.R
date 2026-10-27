run_rnaseq <- function(counts, samples) {
  samples$condition <- factor(samples$condition, levels=c("control", "treatment"))
  dds <- DESeq2::DESeqDataSetFromMatrix(countData=as.matrix(counts), colData=samples, design=~condition)
  dds <- DESeq2::DESeq(dds, quiet=TRUE)
  res <- DESeq2::results(dds, contrast=c("condition", "treatment", "control"))
  list(dds=dds, results=data.frame(gene=rownames(res), log2FoldChange=res$log2FoldChange, pvalue=res$pvalue, padj=res$padj))
}
