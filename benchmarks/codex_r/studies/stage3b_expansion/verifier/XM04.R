# Hidden checks for XM04 (Transcript-to-gene SummarizedExperiment workflow with sequence MD5
# provenance verification, abundance-weighted effective length and sample metadata alignment).
#
# Independent oracle: base-R per-gene/per-sample loop for assay matrices and tools::md5sum() on
# temporary files to cross-check digest::digest(..., algo = "md5", serialize = FALSE).

suppressPackageStartupMessages({
  library(SummarizedExperiment)
  library(digest)
})

xm04_md5_via_tools <- function(s) {
  tf <- tempfile()
  on.exit(unlink(tf), add = TRUE)
  con <- file(tf, open = "wb")
  writeChar(s, con, eos = NULL, useBytes = TRUE)
  close(con)
  unname(tools::md5sum(tf))
}

xm04_make_data <- function(seed) {
  with_seed(seed, {
    tx_ids <- sprintf("TX%03d", 1:14)
    gene_ids <- c(
      "G01", "G01", "G01",
      "G02", "G02",
      "G03", "G03", "G03", "G03",
      "G04",
      "G05", "G05",
      "G98", "G99"
    )
    biotypes <- c(
      rep("protein_coding", 3),
      rep("lncRNA", 2),
      rep("protein_coding", 4),
      "miRNA",
      rep("pseudogene", 2),
      "protein_coding", "lncRNA"
    )
    seqs <- vapply(seq_along(tx_ids), function(i) {
      paste(sample(c("A", "C", "G", "T"), 52L, replace = TRUE), collapse = "")
    }, "")
    md5s <- vapply(seqs, xm04_md5_via_tools, "")
    manifest <- data.frame(
      tx_id = tx_ids,
      gene_id = gene_ids,
      biotype = biotypes,
      sequence = seqs,
      seq_md5 = md5s,
      stringsAsFactors = FALSE
    )[sample.int(length(tx_ids)), , drop = FALSE]
    rownames(manifest) <- NULL

    # Only the first 12 transcripts are quantified (TX013 and TX014 are extra manifest rows)
    q_tx <- sample(sprintf("TX%03d", 1:12))
    samples <- sprintf("S%02d", 1:5)
    cnt <- matrix(as.numeric(stats::rpois(60, lambda = 40)), nrow = 12, dimnames = list(q_tx, samples))
    tpm <- matrix(round(stats::runif(60, 1, 90), 3), nrow = 12, dimnames = list(q_tx, samples))
    # Plant zero-TPM gene-sample cells (all transcripts of G02 in S02 and G05 in S04 have TPM == 0)
    g_map <- stats::setNames(manifest$gene_id, manifest$tx_id)
    tpm[g_map[rownames(tpm)] == "G02", "S02"] <- 0
    tpm[g_map[rownames(tpm)] == "G05", "S04"] <- 0
    eff <- matrix(round(stats::runif(60, 250, 2400), 2), nrow = 12, dimnames = list(q_tx, samples))

    extra_samples <- c(samples, "S99")
    cd <- data.frame(
      condition = c("ctrl", "ctrl", "trt", "trt", "trt", "qc"),
      donor = sprintf("D%d", c(1, 2, 1, 2, 3, 9)),
      row.names = extra_samples,
      stringsAsFactors = FALSE
    )[sample(extra_samples), , drop = FALSE]

    list(counts = cnt, tpm = tpm, eff_len = eff, coldata = cd, tx_manifest = manifest)
  })
}

xm04_oracle <- function(d) {
  tx <- rownames(d$counts)
  smp <- colnames(d$counts)
  m <- d$tx_manifest[match(tx, d$tx_manifest$tx_id), , drop = FALSE]
  genes <- sort(unique(m$gene_id))
  ng <- length(genes)
  ns <- length(smp)

  cnt_g <- matrix(0, nrow = ng, ncol = ns, dimnames = list(genes, smp))
  abd_g <- matrix(0, nrow = ng, ncol = ns, dimnames = list(genes, smp))
  len_g <- matrix(0, nrow = ng, ncol = ns, dimnames = list(genes, smp))
  bio_g <- character(ng)
  ntx_g <- integer(ng)

  for (i in seq_along(genes)) {
    g <- genes[i]
    idx <- which(m$gene_id == g)
    bio_g[i] <- unique(m$biotype[idx])
    ntx_g[i] <- length(idx)
    cnt_g[i, ] <- colSums(d$counts[idx, , drop = FALSE])
    abd_g[i, ] <- colSums(d$tpm[idx, , drop = FALSE])
    for (j in seq_len(ns)) {
      w <- d$tpm[idx, j]
      el <- d$eff_len[idx, j]
      len_g[i, j] <- if (sum(w) > 0) sum(el * w) / sum(w) else mean(el)
    }
  }

  ord_tx <- sort(tx)
  m_ord <- d$tx_manifest[match(ord_tx, d$tx_manifest$tx_id), , drop = FALSE]
  manifest_str <- paste(paste0(m_ord$tx_id, ":", m_ord$seq_md5), collapse = "\n")
  manifest_md5 <- xm04_md5_via_tools(manifest_str)

  list(
    counts = cnt_g,
    abundance = abd_g,
    length = len_g,
    rowData = data.frame(gene_id = genes, biotype = bio_g, n_transcripts = ntx_g, row.names = genes, stringsAsFactors = FALSE),
    colData = d$coldata[smp, , drop = FALSE],
    manifest_md5 = manifest_md5
  )
}

xm04_d <- xm04_make_data(961L)
xm04_want <- xm04_oracle(xm04_d)

local({
  # Verify tools::md5sum matches digest(serialize = FALSE) and differs from serialize = TRUE
  s <- xm04_d$tx_manifest$sequence[1]
  stopifnot(identical(xm04_md5_via_tools(s), digest::digest(s, algo = "md5", serialize = FALSE)))
  stopifnot(!identical(xm04_md5_via_tools(s), digest::digest(s, algo = "md5", serialize = TRUE)))
  # Verify weighted length differs from unweighted mean on non-zero-TPM cells
  g1_idx <- which(xm04_d$tx_manifest$gene_id[match(rownames(xm04_d$counts), xm04_d$tx_manifest$tx_id)] == "G01")
  unw <- colMeans(xm04_d$eff_len[g1_idx, , drop = FALSE])
  stopifnot(max(abs(xm04_want$length["G01", ] - unw)) > 10)
})

xm04_call <- function(d) {
  call_wrapped("summarize_transcriptome", d$counts, d$tpm, d$eff_len, d$coldata, d$tx_manifest)
}

check("returns_valid_summarized_experiment_with_exact_assay_names_and_dimensions", {
  se <- value_of(xm04_call(xm04_d))
  testthat::expect_true( methods::is(se, "SummarizedExperiment") )
  testthat::expect_identical(SummarizedExperiment::assayNames(se), c("counts", "abundance", "length"))
  testthat::expect_identical(rownames(se), rownames(xm04_want$counts))
  testthat::expect_identical(colnames(se), colnames(xm04_want$counts))
})

check("counts_and_abundance_assays_match_gene_level_sums", {
  se <- value_of(xm04_call(xm04_d))
  cnt <- SummarizedExperiment::assay(se, "counts")
  abd <- SummarizedExperiment::assay(se, "abundance")
  testthat::expect_true(is.matrix(cnt) && is.matrix(abd))
  expect_close(cnt, xm04_want$counts, tol = 1e-8, info = "counts")
  expect_close(abd, xm04_want$abundance, tol = 1e-8, info = "abundance")
})

check("length_assay_uses_tpm_weights_and_falls_back_to_unweighted_mean_when_tpm_is_zero", {
  se <- value_of(xm04_call(xm04_d))
  len <- SummarizedExperiment::assay(se, "length")
  testthat::expect_false(anyNA(len))
  expect_close(len, xm04_want$length, tol = 1e-8, info = "length")
})

check("rowdata_and_coldata_preserve_gene_and_sample_alignment_excluding_unquantified_rows", {
  se <- value_of(xm04_call(xm04_d))
  rd <- as.data.frame(SummarizedExperiment::rowData(se))
  cd <- as.data.frame(SummarizedExperiment::colData(se))
  testthat::expect_identical(names(rd), c("gene_id", "biotype", "n_transcripts"))
  testthat::expect_identical(rownames(rd), xm04_want$rowData$gene_id)
  testthat::expect_identical(as.character(rd$gene_id), xm04_want$rowData$gene_id)
  testthat::expect_identical(as.character(rd$biotype), xm04_want$rowData$biotype)
  testthat::expect_identical(as.integer(rd$n_transcripts), xm04_want$rowData$n_transcripts)
  testthat::expect_identical(rownames(cd), rownames(xm04_want$colData))
  testthat::expect_identical(as.character(cd$condition), xm04_want$colData$condition)
  testthat::expect_identical(as.character(cd$donor), xm04_want$colData$donor)
})

check("metadata_manifest_md5_is_computed_over_sorted_quantified_transcripts_without_serialization", {
  se <- value_of(xm04_call(xm04_d))
  md <- S4Vectors::metadata(se)
  testthat::expect_identical(md$manifest_md5, xm04_want$manifest_md5)

  # Reordering rows of tx_manifest or coldata does not change the result
  d2 <- xm04_d
  d2$tx_manifest <- d2$tx_manifest[rev(seq_len(nrow(d2$tx_manifest))), , drop = FALSE]
  d2$coldata <- d2$coldata[rev(seq_len(nrow(d2$coldata))), , drop = FALSE]
  se2 <- value_of(xm04_call(d2))
  testthat::expect_identical(S4Vectors::metadata(se2)$manifest_md5, xm04_want$manifest_md5)
  expect_close(SummarizedExperiment::assay(se2, "length"), xm04_want$length, tol = 1e-8)
})

check("corrupted_sequence_checksum_or_missing_transcript_in_manifest_stops_with_an_error", {
  works <- xm04_call(xm04_d)
  bad_md5 <- xm04_d
  q_idx <- which(bad_md5$tx_manifest$tx_id == rownames(bad_md5$counts)[1])
  bad_md5$tx_manifest$sequence[q_idx] <- paste0(bad_md5$tx_manifest$sequence[q_idx], "A")
  expect_stops(xm04_call(bad_md5), works = works)

  missing_tx <- xm04_d
  missing_tx$tx_manifest <- missing_tx$tx_manifest[-q_idx, , drop = FALSE]
  expect_stops(xm04_call(missing_tx), works = works)

  dup_tx <- xm04_d
  dup_tx$tx_manifest <- rbind(dup_tx$tx_manifest, dup_tx$tx_manifest[1, , drop = FALSE])
  expect_stops(xm04_call(dup_tx), works = works)
})

check("inconsistent_biotype_within_gene_or_missing_sample_in_coldata_stops_with_an_error", {
  works <- xm04_call(xm04_d)
  bad_bio <- xm04_d
  g1_rows <- which(bad_bio$tx_manifest$gene_id == "G01")
  bad_bio$tx_manifest$biotype[g1_rows[1]] <- "snRNA"
  expect_stops(xm04_call(bad_bio), works = works)

  bad_cd <- xm04_d
  bad_cd$coldata <- bad_cd$coldata[rownames(bad_cd$coldata) != "S03", , drop = FALSE]
  expect_stops(xm04_call(bad_cd), works = works)
})

check("mismatched_matrix_dimnames_or_invalid_numeric_values_stop_with_an_error", {
  works <- xm04_call(xm04_d)
  swapped <- xm04_d
  swapped$tpm <- swapped$tpm[rev(seq_len(nrow(swapped$tpm))), , drop = FALSE]
  expect_stops(xm04_call(swapped), works = works)

  neg_cnt <- xm04_d
  neg_cnt$counts[1, 1] <- -1
  expect_stops(xm04_call(neg_cnt), works = works)

  zero_len <- xm04_d
  zero_len$eff_len[2, 2] <- 0
  expect_stops(xm04_call(zero_len), works = works)
})

check("inputs_are_not_modified_and_no_warnings", {
  d <- xm04_d
  res <- xm04_call(d)
  value_of(res)
  expect_no_warnings(res)
  testthat::expect_identical(res$args_after[[1]], d$counts)
  testthat::expect_identical(res$args_after[[4]], d$coldata)
  testthat::expect_identical(res$args_after[[5]], d$tx_manifest)
})

