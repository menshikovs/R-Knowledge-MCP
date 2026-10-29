# Public sample fixture for XM04 (candidate-visible). Seed 2047 is NOT used by any hidden variant.
suppressPackageStartupMessages(library(digest))
set.seed(2047, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
tx_ids <- sprintf("TX%03d", 1:10)
gene_ids <- c("GENE01", "GENE01", "GENE01", "GENE02", "GENE02", "GENE03", "GENE03", "GENE03", "GENE04", "GENE05")
biotypes <- c(rep("protein_coding", 5), rep("lncRNA", 3), "protein_coding", "pseudogene")
seqs <- vapply(1:10, function(i) paste(sample(c("A", "C", "G", "T"), 40L, replace = TRUE), collapse = ""), "")
md5s <- vapply(seqs, digest, "", algo = "md5", serialize = FALSE)
manifest <- data.frame(tx_id = tx_ids, gene_id = gene_ids, biotype = biotypes, sequence = seqs, seq_md5 = unname(md5s), stringsAsFactors = FALSE)
manifest <- manifest[sample.int(nrow(manifest)), ]

keep_tx <- sprintf("TX%03d", 1:8)
samples <- sprintf("SMP%02d", 1:4)
cnt <- matrix(rpois(32, lambda = 45), nrow = 8, dimnames = list(keep_tx, samples))
tpm <- matrix(round(runif(32, 0, 80), 2), nrow = 8, dimnames = list(keep_tx, samples))
tpm[4:5, 2] <- 0
eff <- matrix(round(runif(32, 300, 1800), 1), nrow = 8, dimnames = list(keep_tx, samples))
cd <- data.frame(sample = samples, condition = c("ctrl", "ctrl", "trt", "trt"), batch = c("B1", "B2", "B1", "B2"), stringsAsFactors = FALSE)
cd <- cd[sample.int(nrow(cd)), ]

out_dir <- Sys.getenv("OUT_DIR", "/out")
write.csv(cnt, file.path(out_dir, "tx_counts.csv"))
write.csv(tpm, file.path(out_dir, "tx_tpm.csv"))
write.csv(eff, file.path(out_dir, "tx_efflen.csv"))
write.csv(cd, file.path(out_dir, "coldata.csv"), row.names = FALSE)
write.csv(manifest, file.path(out_dir, "tx_manifest.csv"), row.names = FALSE)

