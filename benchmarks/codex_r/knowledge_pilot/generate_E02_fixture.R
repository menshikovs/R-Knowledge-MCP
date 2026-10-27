# Trusted offline fixture generator; never exported to the agent workspace.
# Run with R 4.5.2: Rscript --vanilla generate_E02_fixture.R [output.csv]
stopifnot(as.character(getRversion()) == "4.5.2")
RNGkind("Mersenne-Twister", "Inversion", "Rejection")
set.seed(20261025L)
n_genes <- 500L
samples <- c("ctrl_1", "ctrl_2", "ctrl_3", "treat_1", "treat_2", "treat_3")
baseline <- exp(stats::rnorm(n_genes, log(120), 1))
# Gene-specific biological dispersion, including a realistic mean relationship.
dispersion <- (0.08 + 12 / baseline) *
  stats::rlnorm(n_genes, -0.5 * 0.35^2, 0.35)
fold_change <- rep(1, n_genes)
fold_change[1:10] <- 4
fold_change[11:20] <- 0.25
library_factors <- c(0.85, 1, 1.15, 0.9, 1.05, 1.1)
counts <- vapply(seq_along(samples), function(j) {
  mu <- baseline * library_factors[j] * if (j > 3L) fold_change else 1
  as.integer(stats::rnbinom(n_genes, mu=mu, size=1 / dispersion))
}, integer(n_genes))
colnames(counts) <- samples
output <- data.frame(gene=paste0("gene_", seq_len(n_genes)), counts, check.names=FALSE)
stopifnot(all(counts >= 0L), !anyNA(counts), nrow(output) == n_genes)
args <- commandArgs(trailingOnly=TRUE)
script <- sub("^--file=", "", grep("^--file=", commandArgs(), value=TRUE)[[1L]])
target <- if (length(args)) args[[1L]] else
  file.path(dirname(normalizePath(script)), "fixtures", "E02-counts.csv")
utils::write.table(output, target, sep=",", row.names=FALSE, quote=FALSE, eol="\n")
cat("Generated", n_genes, "genes x", length(samples), "samples; seed 20261025\n")
