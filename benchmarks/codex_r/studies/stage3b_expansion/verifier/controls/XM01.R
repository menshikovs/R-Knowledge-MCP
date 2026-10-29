#### control: reference
# Trusted reference: DESeq2 with explicit levels, batch in the design, alpha for the filtering.
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  if (!is.matrix(counts) || anyNA(counts) || any(counts < 0) || any(counts != round(counts))) stop("counts must be a matrix of non-negative integers")
  if (!all(colnames(counts) %in% rownames(coldata))) stop("sample without coldata")
  lv <- unique(coldata$condition)
  if (!all(c(contrast_level, reference_level) %in% lv) || identical(contrast_level, reference_level)) stop("bad levels")
  cd <- coldata[colnames(counts), , drop = FALSE]
  cd$condition <- factor(cd$condition, levels = c(reference_level, contrast_level))
  cd$batch <- factor(cd$batch)
  dds <- DESeqDataSetFromMatrix(countData = counts, colData = cd, design = ~ batch + condition)
  dds <- DESeq(dds, quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", contrast_level, reference_level), alpha = alpha))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(res$padj, res$pvalue, res$gene), ]
  rownames(res) <- NULL
  res
}

#### control: alternate_coefficient_name_and_relevel
# Alternate valid solution: relevel() and results(name = ...).
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  stopifnot(is.matrix(counts), !anyNA(counts), all(counts >= 0), all(counts == round(counts)),
            all(colnames(counts) %in% rownames(coldata)),
            all(c(contrast_level, reference_level) %in% coldata$condition), contrast_level != reference_level)
  cd <- coldata[colnames(counts), c("condition", "batch")]
  cd$condition <- relevel(factor(cd$condition), ref = reference_level)
  cd$batch <- factor(cd$batch)
  dds <- DESeq(DESeqDataSetFromMatrix(counts, cd, ~ batch + condition), quiet = TRUE)
  nm <- paste0("condition_", contrast_level, "_vs_", reference_level)
  r <- as.data.frame(results(dds, name = nm, alpha = alpha))
  r$gene <- rownames(r)
  r <- subset(r, !is.na(padj) & padj < alpha, select = c(gene, baseMean, log2FoldChange, pvalue, padj))
  r <- r[order(r$padj, r$pvalue, r$gene), ]
  rownames(r) <- NULL
  r
}

#### control: wrong_default_alphabetical_reference
# Plausible wrong strategy: factor() default levels, so the reference is the alphabetically first level.
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  stopifnot(is.matrix(counts), !anyNA(counts), all(counts >= 0), all(counts == round(counts)),
            all(colnames(counts) %in% rownames(coldata)),
            all(c(contrast_level, reference_level) %in% coldata$condition), contrast_level != reference_level)
  cd <- coldata[colnames(counts), , drop = FALSE]
  cd$condition <- factor(cd$condition)
  cd$batch <- factor(cd$batch)
  dds <- DESeq(DESeqDataSetFromMatrix(counts, cd, ~ batch + condition), quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", contrast_level, reference_level), alpha = alpha))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(res$padj, res$pvalue, res$gene), ]
  rownames(res) <- NULL
  res
}

#### control: wrong_no_batch_covariate
# Plausible wrong strategy: batch left out of the design.
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  stopifnot(is.matrix(counts), !anyNA(counts), all(counts >= 0), all(counts == round(counts)),
            all(colnames(counts) %in% rownames(coldata)),
            all(c(contrast_level, reference_level) %in% coldata$condition), contrast_level != reference_level)
  cd <- coldata[colnames(counts), , drop = FALSE]
  cd$condition <- factor(cd$condition, levels = c(reference_level, contrast_level))
  dds <- DESeq(DESeqDataSetFromMatrix(counts, cd, ~ condition), quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", contrast_level, reference_level), alpha = alpha))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(res$padj, res$pvalue, res$gene), ]
  rownames(res) <- NULL
  res
}

#### control: wrong_alpha_only_in_the_final_filter
# Plausible wrong strategy: results() keeps its default alpha (0.1) for independent filtering.
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  stopifnot(is.matrix(counts), !anyNA(counts), all(counts >= 0), all(counts == round(counts)),
            all(colnames(counts) %in% rownames(coldata)),
            all(c(contrast_level, reference_level) %in% coldata$condition), contrast_level != reference_level)
  cd <- coldata[colnames(counts), , drop = FALSE]
  cd$condition <- factor(cd$condition, levels = c(reference_level, contrast_level))
  cd$batch <- factor(cd$batch)
  dds <- DESeq(DESeqDataSetFromMatrix(counts, cd, ~ batch + condition), quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", contrast_level, reference_level)))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(res$padj, res$pvalue, res$gene), ]
  rownames(res) <- NULL
  res
}

#### control: wrong_sample_names_overwritten
# Plausible wrong strategy: coldata row names are overwritten with the column names, silently mis-assigning samples.
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  stopifnot(is.matrix(counts), !anyNA(counts), all(counts >= 0), all(counts == round(counts)),
            all(c(contrast_level, reference_level) %in% coldata$condition), contrast_level != reference_level)
  cd <- coldata
  rownames(cd) <- colnames(counts)
  cd$condition <- factor(cd$condition, levels = c(reference_level, contrast_level))
  cd$batch <- factor(cd$batch)
  dds <- DESeq(DESeqDataSetFromMatrix(counts, cd, ~ batch + condition), quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", contrast_level, reference_level), alpha = alpha))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(res$padj, res$pvalue, res$gene), ]
  rownames(res) <- NULL
  res
}

#### control: wrong_sorted_by_fold_change
# Plausible wrong strategy: significant genes ordered by effect size.
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  stopifnot(is.matrix(counts), !anyNA(counts), all(counts >= 0), all(counts == round(counts)),
            all(colnames(counts) %in% rownames(coldata)),
            all(c(contrast_level, reference_level) %in% coldata$condition), contrast_level != reference_level)
  cd <- coldata[colnames(counts), , drop = FALSE]
  cd$condition <- factor(cd$condition, levels = c(reference_level, contrast_level))
  cd$batch <- factor(cd$batch)
  dds <- DESeq(DESeqDataSetFromMatrix(counts, cd, ~ batch + condition), quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", contrast_level, reference_level), alpha = alpha))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(-abs(res$log2FoldChange)), ]
  rownames(res) <- NULL
  res
}

#### control: edge_no_input_validation
# Boundary case: right for valid input but invalid input is not rejected (expected: not fully correct).
# expect: fail
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  cd <- coldata[colnames(counts), , drop = FALSE]
  cd$condition <- factor(cd$condition, levels = c(reference_level, contrast_level))
  cd$batch <- factor(cd$batch)
  dds <- DESeq(DESeqDataSetFromMatrix(round(abs(counts)), cd, ~ batch + condition), quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", contrast_level, reference_level), alpha = alpha))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(res$padj, res$pvalue, res$gene), ]
  rownames(res) <- NULL
  res
}

#### control: malformed_returns_deseq_results
# Malformed submission: the DESeqResults object.
# expect: fail
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) {
  suppressPackageStartupMessages(library(DESeq2))
  cd <- coldata[colnames(counts), , drop = FALSE]
  cd$condition <- factor(cd$condition, levels = c(reference_level, contrast_level))
  results(DESeq(DESeqDataSetFromMatrix(counts, cd, ~ condition), quiet = TRUE))
}

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
differential_expression <- function(counts, coldata, contrast_level, reference_level, alpha = 0.05) stop("todo")
