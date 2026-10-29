# Hidden checks for XM01 (DESeq2 workflow with a batch covariate, contrast direction, alpha and
# sample alignment).
#
# Oracle: the canonical DESeq2 pipeline written with explicit factor levels and an explicit
# contrast. Because the estimator itself is DESeq2, independence comes from planted truth and
# hand-computed quantities: the median-of-ratios size factors and baseMean are recomputed in plain
# R and compared at load time, and the planted up/down genes must have the planted sign.

suppressPackageStartupMessages(library(DESeq2))

xm01_data <- function(seed, n_genes = 120L, all_null = FALSE) {
  with_seed(seed, {
    samples <- sprintf("S%02d", 1:12)
    cond <- rep(c("control", "treated"), each = 6)
    batch <- rep(rep(c("b1", "b2", "b3"), each = 2), 2)
    n_high <- n_genes %/% 2L
    base <- if (all_null) {
      exp(stats::rnorm(n_genes, 5.5, 1))
    } else {
      c(exp(stats::rnorm(15L, 5.5, 0.4)), exp(stats::rnorm(n_high - 15L, 5.0, 0.6)), rep(0.8, n_genes - n_high))
    }
    lfc <- rep(0, n_genes)
    if (!all_null) {
      lfc[1:9] <- c(rep(1.6, 4), rep(0.95, 4), 0.72)
      lfc[10:15] <- c(rep(-1.6, 3), rep(-0.95, 3))
    }
    beff <- matrix(stats::rnorm(n_genes * 3, 0, 0.5), n_genes, 3)
    mu <- sapply(seq_along(samples), function(j) {
      base * 2^(lfc * (cond[j] == "treated") + beff[, as.integer(sub("b", "", batch[j]))])
    })
    cnt <- matrix(stats::rnbinom(length(mu), mu = mu, size = 15), nrow = n_genes,
                  dimnames = list(sprintf("g%03d", seq_len(n_genes)), samples))
    cd <- data.frame(condition = cond, batch = batch, row.names = samples, stringsAsFactors = FALSE)
    list(counts = cnt, coldata = cd[sample(samples), , drop = FALSE])
  })
}

xm01_oracle <- function(d, lev, ref, alpha = 0.05, batch = TRUE, filter_alpha = alpha) {
  cd <- d$coldata[colnames(d$counts), , drop = FALSE]
  cd$condition <- factor(cd$condition, levels = c(ref, lev))
  cd$batch <- factor(cd$batch)
  dds <- DESeqDataSetFromMatrix(countData = d$counts, colData = cd,
                                design = if (batch) ~ batch + condition else ~ condition)
  dds <- DESeq(dds, quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", lev, ref), alpha = filter_alpha))
  res$gene <- rownames(res)
  res <- res[!is.na(res$padj) & res$padj < alpha, c("gene", "baseMean", "log2FoldChange", "pvalue", "padj")]
  res <- res[order(res$padj, res$pvalue, res$gene), ]
  rownames(res) <- NULL
  res
}

xm01_a <- xm01_data(931L)
xm01_c <- xm01_data(933L, n_genes = 60L, all_null = TRUE)
xm01_o_a <- xm01_oracle(xm01_a, "treated", "control")
xm01_o_flip <- xm01_oracle(xm01_a, "control", "treated")
xm01_o_a01 <- xm01_oracle(xm01_a, "treated", "control", alpha = 0.01)
xm01_o_a01_default_filt <- xm01_oracle(xm01_a, "treated", "control", alpha = 0.01, filter_alpha = 0.10)
xm01_o_nobatch <- xm01_oracle(xm01_a, "treated", "control", batch = FALSE)
xm01_o_c <- xm01_oracle(xm01_c, "treated", "control")

local({
  stopifnot(nrow(xm01_o_a) >= 8L, nrow(xm01_o_c) == 0L, nrow(xm01_o_a01) < nrow(xm01_o_a))
  stopifnot(nrow(xm01_o_a01) != nrow(xm01_o_a01_default_filt) || !isTRUE(all.equal(xm01_o_a01$padj, xm01_o_a01_default_filt$padj)))
  up <- sprintf("g%03d", 1:9)
  down <- sprintf("g%03d", 10:15)
  stopifnot(all(xm01_o_a$log2FoldChange[xm01_o_a$gene %in% up] > 0), all(xm01_o_a$log2FoldChange[xm01_o_a$gene %in% down] < 0))
  stopifnot(all(xm01_o_flip$log2FoldChange[xm01_o_flip$gene %in% up] < 0))
  # the batch term and the alpha-matched independent filtering must matter, otherwise they are untested
  stopifnot(!isTRUE(all.equal(xm01_o_a$padj, xm01_o_nobatch$padj[seq_len(nrow(xm01_o_a))])) || nrow(xm01_o_a) != nrow(xm01_o_nobatch))
  # hand-computed median-of-ratios size factors and baseMean
  cnt <- xm01_a$counts
  loggeo <- rowMeans(log(cnt))
  ok <- is.finite(loggeo)
  sf <- apply(cnt, 2, function(x) exp(stats::median((log(x) - loggeo)[ok])))
  bm <- rowMeans(sweep(cnt, 2, sf, "/"))
  chk <- merge(xm01_o_a, data.frame(gene = names(bm), bm = unname(bm)), by = "gene")
  stopifnot(isTRUE(all.equal(chk$baseMean, chk$bm, tolerance = 1e-6)))
})

xm01_call <- function(d, lev = "treated", ref = "control", ...) {
  call_wrapped("differential_expression", d$counts, d$coldata, lev, ref, ...)
}

xm01_same <- function(got, want) {
  testthat::expect_true(is.data.frame(got))
  testthat::expect_identical(names(got), c("gene", "baseMean", "log2FoldChange", "pvalue", "padj"))
  testthat::expect_identical(nrow(got), nrow(want))
  testthat::expect_identical(as.character(got$gene), want$gene)
  for (nm in c("baseMean", "log2FoldChange", "pvalue", "padj")) {
    expect_close(got[[nm]], want[[nm]], tol = 1e-6, info = nm)
  }
}

check("significant_genes_and_statistics_match_the_batch_adjusted_model", {
  xm01_same(as.data.frame(value_of(xm01_call(xm01_a))), xm01_o_a)
})

check("contrast_direction_follows_contrast_level_over_reference_level", {
  got <- as.data.frame(value_of(xm01_call(xm01_a, "control", "treated")))
  xm01_same(got, xm01_o_flip)
  up <- sprintf("g%03d", 1:9)
  testthat::expect_true(all(got$log2FoldChange[got$gene %in% up] < 0))
})

check("alpha_controls_both_the_cutoff_and_independent_filtering", {
  xm01_same(as.data.frame(value_of(xm01_call(xm01_a, alpha = 0.01))), xm01_o_a01)
})

check("batch_is_included_in_the_design", {
  got <- as.data.frame(value_of(xm01_call(xm01_a)))
  testthat::expect_false(isTRUE(all.equal(got$padj, xm01_o_nobatch$padj[seq_len(nrow(got))])) && nrow(got) == nrow(xm01_o_nobatch))
  expect_close(got$log2FoldChange, xm01_o_a$log2FoldChange, tol = 1e-6)
})

check("samples_are_matched_by_name_when_coldata_is_in_another_order", {
  d <- xm01_a
  d$coldata <- d$coldata[rev(rownames(d$coldata)), , drop = FALSE]
  xm01_same(as.data.frame(value_of(xm01_call(d))), xm01_o_a)
})

check("only_genes_with_padj_below_alpha_are_returned_in_the_specified_order", {
  got <- as.data.frame(value_of(xm01_call(xm01_a)))
  testthat::expect_false(anyNA(got$padj))
  testthat::expect_true(all(got$padj < 0.05))
  testthat::expect_false(is.unsorted(got$padj))
})

check("no_significant_gene_gives_a_zero_row_data_frame_with_the_same_columns", {
  got <- as.data.frame(value_of(xm01_call(xm01_c)))
  testthat::expect_identical(nrow(got), 0L)
  testthat::expect_identical(names(got), c("gene", "baseMean", "log2FoldChange", "pvalue", "padj"))
  testthat::expect_true(is.character(got$gene) && is.numeric(got$padj))
})

check("result_is_a_plain_data_frame_with_default_row_names", {
  got <- value_of(xm01_call(xm01_a))
  testthat::expect_false(inherits(got, "DFrame"))
  testthat::expect_identical(rownames(got), as.character(seq_len(nrow(got))))
  testthat::expect_true(is.character(got$gene))
})

check("invalid_inputs_are_errors", {
  works <- xm01_call(xm01_a)
  expect_stops(xm01_call(xm01_a, "nosuchlevel", "control"), works = works)
  expect_stops(xm01_call(xm01_a, "treated", "treated"), works = works)
  neg <- xm01_a
  neg$counts[1, 1] <- -1L
  expect_stops(xm01_call(neg), works = works)
  frac <- xm01_a
  frac$counts <- frac$counts + 0.5
  expect_stops(xm01_call(frac), works = works)
  missing_sample <- xm01_a
  missing_sample$coldata <- missing_sample$coldata[-1, , drop = FALSE]
  expect_stops(xm01_call(missing_sample), works = works)
})

check("inputs_are_not_modified_and_no_warnings", {
  d <- xm01_a
  res <- xm01_call(d)
  value_of(res)
  expect_no_warnings(res)
  testthat::expect_identical(res$args_after[[1]], d$counts)
  testthat::expect_identical(res$args_after[[2]], d$coldata)
})
