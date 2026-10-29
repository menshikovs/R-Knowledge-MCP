#### control: reference
# Trusted reference: sequence MD5 verification via digest(serialize = FALSE), rowsum + weighted length with zero-TPM fallback.
summarize_transcriptome <- function(counts, tpm, eff_len, coldata, tx_manifest) {
  suppressPackageStartupMessages({
    library(SummarizedExperiment)
    library(digest)
  })
  for (mat in list(counts, tpm, eff_len)) {
    if (!is.matrix(mat) || !is.numeric(mat) || nrow(mat) < 1L || ncol(mat) < 1L || anyNA(mat)) {
      stop("inputs must be non-empty numeric matrices without NA")
    }
  }
  tx <- rownames(counts)
  smp <- colnames(counts)
  if (is.null(tx) || is.null(smp) || anyDuplicated(tx) || anyDuplicated(smp)) stop("missing or duplicate dimnames")
  if (!identical(dim(counts), dim(tpm)) || !identical(dim(counts), dim(eff_len)) ||
      !identical(rownames(tpm), tx) || !identical(rownames(eff_len), tx) ||
      !identical(colnames(tpm), smp) || !identical(colnames(eff_len), smp)) {
    stop("matrix dimensions or dimnames do not match")
  }
  if (any(counts < 0) || any(tpm < 0) || any(eff_len <= 0)) stop("invalid numeric matrix values")
  if (!is.data.frame(coldata) || is.null(rownames(coldata)) || !all(smp %in% rownames(coldata))) {
    stop("coldata missing required sample rows")
  }
  req_cols <- c("tx_id", "gene_id", "biotype", "sequence", "seq_md5")
  if (!is.data.frame(tx_manifest) || !all(req_cols %in% names(tx_manifest)) || anyNA(tx_manifest[, req_cols]) ||
      anyDuplicated(tx_manifest$tx_id) || !all(tx %in% tx_manifest$tx_id)) {
    stop("invalid tx_manifest")
  }

  m <- tx_manifest[match(tx, tx_manifest$tx_id), , drop = FALSE]
  calc_md5 <- vapply(as.character(m$sequence), digest::digest, "", algo = "md5", serialize = FALSE)
  if (!identical(unname(calc_md5), as.character(m$seq_md5))) stop("sequence MD5 mismatch")

  genes <- sort(unique(as.character(m$gene_id)))
  bio_by_gene <- vapply(genes, function(g) {
    b <- unique(as.character(m$biotype[m$gene_id == g]))
    if (length(b) != 1L) stop("inconsistent biotype within gene")
    b
  }, "")
  ntx_by_gene <- vapply(genes, function(g) sum(m$gene_id == g), 0L)

  cnt_g <- rowsum(counts, group = m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  abd_g <- rowsum(tpm, group = m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  num_g <- rowsum(eff_len * tpm, group = m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  sum_len_g <- rowsum(eff_len, group = m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  mean_len_g <- sweep(sum_len_g, 1, ntx_by_gene, "/")
  len_g <- ifelse(abd_g > 0, num_g / abd_g, mean_len_g)
  dimnames(len_g) <- dimnames(cnt_g)

  rd <- data.frame(
    gene_id = genes,
    biotype = unname(bio_by_gene),
    n_transcripts = as.integer(unname(ntx_by_gene)),
    row.names = genes,
    stringsAsFactors = FALSE
  )
  cd <- coldata[smp, , drop = FALSE]

  ord_tx <- sort(tx)
  m_ord <- m[match(ord_tx, m$tx_id), , drop = FALSE]
  manifest_md5 <- digest::digest(
    paste(paste0(m_ord$tx_id, ":", m_ord$seq_md5), collapse = "\n"),
    algo = "md5",
    serialize = FALSE
  )

  SummarizedExperiment::SummarizedExperiment(
    assays = list(counts = cnt_g, abundance = abd_g, length = len_g),
    rowData = rd,
    colData = cd,
    metadata = list(manifest_md5 = manifest_md5)
  )
}

#### control: alternate_split_by_gene_loop
# Alternate valid solution: explicit split-by-gene aggregation and S4 DataFrame rowData/colData.
summarize_transcriptome <- function(counts, tpm, eff_len, coldata, tx_manifest) {
  suppressPackageStartupMessages({
    library(SummarizedExperiment)
    library(S4Vectors)
    library(digest)
  })
  stopifnot(is.matrix(counts), is.matrix(tpm), is.matrix(eff_len),
            is.numeric(counts), is.numeric(tpm), is.numeric(eff_len),
            nrow(counts) >= 1L, ncol(counts) >= 1L,
            !anyNA(counts), !anyNA(tpm), !anyNA(eff_len),
            identical(dim(counts), dim(tpm)), identical(dim(counts), dim(eff_len)),
            !is.null(rownames(counts)), !is.null(colnames(counts)),
            !anyDuplicated(rownames(counts)), !anyDuplicated(colnames(counts)),
            identical(rownames(counts), rownames(tpm)), identical(rownames(counts), rownames(eff_len)),
            identical(colnames(counts), colnames(tpm)), identical(colnames(counts), colnames(eff_len)),
            all(counts >= 0), all(tpm >= 0), all(eff_len > 0),
            is.data.frame(coldata), all(colnames(counts) %in% rownames(coldata)),
            is.data.frame(tx_manifest),
            all(c("tx_id", "gene_id", "biotype", "sequence", "seq_md5") %in% names(tx_manifest)),
            !anyDuplicated(tx_manifest$tx_id), all(rownames(counts) %in% tx_manifest$tx_id))
  m <- tx_manifest[match(rownames(counts), tx_manifest$tx_id), , drop = FALSE]
  for (i in seq_len(nrow(m))) {
    if (!identical(digest(m$sequence[i], algo = "md5", serialize = FALSE), m$seq_md5[i])) stop("bad md5")
  }
  genes <- sort(unique(m$gene_id))
  smp <- colnames(counts)
  cnt_g <- matrix(0, length(genes), length(smp), dimnames = list(genes, smp))
  abd_g <- cnt_g
  len_g <- cnt_g
  bio <- character(length(genes))
  ntx <- integer(length(genes))
  for (k in seq_along(genes)) {
    idx <- which(m$gene_id == genes[k])
    ub <- unique(m$biotype[idx])
    stopifnot(length(ub) == 1L)
    bio[k] <- ub
    ntx[k] <- length(idx)
    cnt_g[k, ] <- colSums(counts[idx, , drop = FALSE])
    abd_g[k, ] <- colSums(tpm[idx, , drop = FALSE])
    len_g[k, ] <- vapply(seq_along(smp), function(j) {
      w <- tpm[idx, j]
      if (sum(w) == 0) mean(eff_len[idx, j]) else sum(eff_len[idx, j] * w) / sum(w)
    }, 0)
  }
  ord <- order(m$tx_id)
  m_hash <- digest(paste(paste0(m$tx_id[ord], ":", m$seq_md5[ord]), collapse = "\n"), algo = "md5", serialize = FALSE)
  SummarizedExperiment(
    assays = SimpleList(counts = cnt_g, abundance = abd_g, length = len_g),
    rowData = DataFrame(gene_id = genes, biotype = bio, n_transcripts = ntx, row.names = genes),
    colData = DataFrame(coldata[smp, , drop = FALSE]),
    metadata = list(manifest_md5 = m_hash)
  )
}

#### control: wrong_unweighted_effective_length
# Plausible wrong strategy: takes the unweighted mean of eff_len across isoforms instead of weighting by tpm.
summarize_transcriptome <- function(counts, tpm, eff_len, coldata, tx_manifest) {
  suppressPackageStartupMessages({ library(SummarizedExperiment); library(digest) })
  stopifnot(is.matrix(counts), is.matrix(tpm), is.matrix(eff_len), !anyNA(counts), !anyNA(tpm), !anyNA(eff_len),
            identical(dim(counts), dim(tpm)), identical(dim(counts), dim(eff_len)),
            identical(rownames(counts), rownames(tpm)), identical(rownames(counts), rownames(eff_len)),
            identical(colnames(counts), colnames(tpm)), identical(colnames(counts), colnames(eff_len)),
            all(counts >= 0), all(tpm >= 0), all(eff_len > 0),
            all(colnames(counts) %in% rownames(coldata)), !anyDuplicated(tx_manifest$tx_id),
            all(rownames(counts) %in% tx_manifest$tx_id))
  m <- tx_manifest[match(rownames(counts), tx_manifest$tx_id), , drop = FALSE]
  stopifnot(identical(unname(vapply(m$sequence, digest, "", algo = "md5", serialize = FALSE)), m$seq_md5))
  genes <- sort(unique(m$gene_id))
  bio <- vapply(genes, function(g) { b <- unique(m$biotype[m$gene_id == g]); stopifnot(length(b) == 1L); b }, "")
  ntx <- vapply(genes, function(g) sum(m$gene_id == g), 0L)
  cnt_g <- rowsum(counts, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  abd_g <- rowsum(tpm, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  len_g <- sweep(rowsum(eff_len, m$gene_id, reorder = TRUE)[genes, , drop = FALSE], 1, ntx, "/")
  ord <- order(m$tx_id)
  m_hash <- digest(paste(paste0(m$tx_id[ord], ":", m$seq_md5[ord]), collapse = "\n"), algo = "md5", serialize = FALSE)
  SummarizedExperiment(
    assays = list(counts = cnt_g, abundance = abd_g, length = len_g),
    rowData = data.frame(gene_id = genes, biotype = unname(bio), n_transcripts = as.integer(unname(ntx)), row.names = genes),
    colData = coldata[colnames(counts), , drop = FALSE],
    metadata = list(manifest_md5 = m_hash)
  )
}

#### control: wrong_no_zero_tpm_fallback
# Plausible wrong strategy: divides rowsum(eff_len * tpm) by rowsum(tpm) without falling back when sum(tpm) == 0 (produces NaN).
summarize_transcriptome <- function(counts, tpm, eff_len, coldata, tx_manifest) {
  suppressPackageStartupMessages({ library(SummarizedExperiment); library(digest) })
  stopifnot(is.matrix(counts), is.matrix(tpm), is.matrix(eff_len), !anyNA(counts), !anyNA(tpm), !anyNA(eff_len),
            identical(dim(counts), dim(tpm)), identical(dim(counts), dim(eff_len)),
            identical(rownames(counts), rownames(tpm)), identical(rownames(counts), rownames(eff_len)),
            identical(colnames(counts), colnames(tpm)), identical(colnames(counts), colnames(eff_len)),
            all(counts >= 0), all(tpm >= 0), all(eff_len > 0),
            all(colnames(counts) %in% rownames(coldata)), !anyDuplicated(tx_manifest$tx_id),
            all(rownames(counts) %in% tx_manifest$tx_id))
  m <- tx_manifest[match(rownames(counts), tx_manifest$tx_id), , drop = FALSE]
  stopifnot(identical(unname(vapply(m$sequence, digest, "", algo = "md5", serialize = FALSE)), m$seq_md5))
  genes <- sort(unique(m$gene_id))
  bio <- vapply(genes, function(g) { b <- unique(m$biotype[m$gene_id == g]); stopifnot(length(b) == 1L); b }, "")
  ntx <- vapply(genes, function(g) sum(m$gene_id == g), 0L)
  cnt_g <- rowsum(counts, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  abd_g <- rowsum(tpm, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  len_g <- rowsum(eff_len * tpm, m$gene_id, reorder = TRUE)[genes, , drop = FALSE] / abd_g
  ord <- order(m$tx_id)
  m_hash <- digest(paste(paste0(m$tx_id[ord], ":", m$seq_md5[ord]), collapse = "\n"), algo = "md5", serialize = FALSE)
  SummarizedExperiment(
    assays = list(counts = cnt_g, abundance = abd_g, length = len_g),
    rowData = data.frame(gene_id = genes, biotype = unname(bio), n_transcripts = as.integer(unname(ntx)), row.names = genes),
    colData = coldata[colnames(counts), , drop = FALSE],
    metadata = list(manifest_md5 = m_hash)
  )
}

#### control: wrong_manifest_md5_uses_full_manifest
# Plausible wrong strategy: computes manifest_md5 over all rows of tx_manifest instead of the sorted quantified transcripts.
summarize_transcriptome <- function(counts, tpm, eff_len, coldata, tx_manifest) {
  suppressPackageStartupMessages({ library(SummarizedExperiment); library(digest) })
  stopifnot(is.matrix(counts), is.matrix(tpm), is.matrix(eff_len), !anyNA(counts), !anyNA(tpm), !anyNA(eff_len),
            identical(dim(counts), dim(tpm)), identical(dim(counts), dim(eff_len)),
            identical(rownames(counts), rownames(tpm)), identical(rownames(counts), rownames(eff_len)),
            identical(colnames(counts), colnames(tpm)), identical(colnames(counts), colnames(eff_len)),
            all(counts >= 0), all(tpm >= 0), all(eff_len > 0),
            all(colnames(counts) %in% rownames(coldata)), !anyDuplicated(tx_manifest$tx_id),
            all(rownames(counts) %in% tx_manifest$tx_id))
  m <- tx_manifest[match(rownames(counts), tx_manifest$tx_id), , drop = FALSE]
  stopifnot(identical(unname(vapply(m$sequence, digest, "", algo = "md5", serialize = FALSE)), m$seq_md5))
  genes <- sort(unique(m$gene_id))
  bio <- vapply(genes, function(g) { b <- unique(m$biotype[m$gene_id == g]); stopifnot(length(b) == 1L); b }, "")
  ntx <- vapply(genes, function(g) sum(m$gene_id == g), 0L)
  cnt_g <- rowsum(counts, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  abd_g <- rowsum(tpm, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  num_g <- rowsum(eff_len * tpm, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  mean_len_g <- sweep(rowsum(eff_len, m$gene_id, reorder = TRUE)[genes, , drop = FALSE], 1, ntx, "/")
  len_g <- ifelse(abd_g > 0, num_g / abd_g, mean_len_g)
  dimnames(len_g) <- dimnames(cnt_g)
  m_hash <- digest(paste(paste0(tx_manifest$tx_id, ":", tx_manifest$seq_md5), collapse = "\n"), algo = "md5", serialize = FALSE)
  SummarizedExperiment(
    assays = list(counts = cnt_g, abundance = abd_g, length = len_g),
    rowData = data.frame(gene_id = genes, biotype = unname(bio), n_transcripts = as.integer(unname(ntx)), row.names = genes),
    colData = coldata[colnames(counts), , drop = FALSE],
    metadata = list(manifest_md5 = m_hash)
  )
}

#### control: edge_no_checksum_or_input_validation
# Boundary case: skips sequence MD5 check, biotype consistency check and matrix validation.
# expect: fail
summarize_transcriptome <- function(counts, tpm, eff_len, coldata, tx_manifest) {
  suppressPackageStartupMessages({ library(SummarizedExperiment); library(digest) })
  m <- tx_manifest[match(rownames(counts), tx_manifest$tx_id), , drop = FALSE]
  genes <- sort(unique(m$gene_id))
  bio <- vapply(genes, function(g) m$biotype[m$gene_id == g][1], "")
  ntx <- vapply(genes, function(g) sum(m$gene_id == g), 0L)
  cnt_g <- rowsum(counts, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  abd_g <- rowsum(tpm, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  num_g <- rowsum(eff_len * tpm, m$gene_id, reorder = TRUE)[genes, , drop = FALSE]
  mean_len_g <- sweep(rowsum(eff_len, m$gene_id, reorder = TRUE)[genes, , drop = FALSE], 1, ntx, "/")
  len_g <- ifelse(abd_g > 0, num_g / abd_g, mean_len_g)
  dimnames(len_g) <- dimnames(cnt_g)
  ord <- order(m$tx_id)
  m_hash <- digest(paste(paste0(m$tx_id[ord], ":", m$seq_md5[ord]), collapse = "\n"), algo = "md5", serialize = FALSE)
  SummarizedExperiment(
    assays = list(counts = cnt_g, abundance = abd_g, length = len_g),
    rowData = data.frame(gene_id = genes, biotype = unname(bio), n_transcripts = as.integer(unname(ntx)), row.names = genes),
    colData = coldata[colnames(counts), , drop = FALSE],
    metadata = list(manifest_md5 = m_hash)
  )
}

#### control: malformed_returns_plain_list
# Malformed submission: returns a plain list instead of a SummarizedExperiment object.
# expect: fail
summarize_transcriptome <- function(counts, tpm, eff_len, coldata, tx_manifest) {
  list(counts = counts, abundance = tpm, length = eff_len)
}

