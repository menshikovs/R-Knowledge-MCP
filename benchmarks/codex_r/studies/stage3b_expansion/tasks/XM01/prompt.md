# XM01: Differential expression with a batch covariate

A small RNA-seq experiment compares `treated` with `control` samples, processed in three batches.
A sample is in `data/counts.csv` (genes in rows, samples in columns, raw integer counts) and
`data/coldata.csv` (columns `sample`, `condition`, `batch`; one row per sample, **in no particular
order**). The analysis must use the Bioconductor packages installed in the supplied environment
(versions recorded in `renv.lock`); do not install anything.

Write `solution.R` defining
`differential_expression(counts, coldata, contrast_level, reference_level, alpha = 0.05)`.

- `counts` is an integer matrix with gene names as row names and sample names as column names.
- `coldata` is a data frame whose **row names are the sample names**, with the character columns
  `condition` and `batch`. Its rows are **not necessarily in the same order** as the columns of
  `counts`; samples must be matched by name.
- `contrast_level` and `reference_level` are two values of `condition`; the comparison is
  `contrast_level` **relative to** `reference_level` (a positive log2 fold change means higher
  expression in `contrast_level`).

## What to compute

Fit a negative-binomial model of the counts with the design `~ batch + condition` (batch as a
nuisance covariate, `condition` of interest) using DESeq2's standard workflow, and test the
condition contrast at significance level `alpha`. Use `alpha` for both the false-discovery-rate
cut-off **and** DESeq2's independent filtering, so that the adjusted p-values correspond to the
requested level.

## Return value

A plain data frame with exactly the columns `gene`, `baseMean`, `log2FoldChange`, `pvalue` and
`padj`, containing **only the genes with `padj < alpha`** (genes with a missing `padj` are
excluded), ordered by increasing `padj`, then increasing `pvalue`, then `gene`. Row names are
`1, 2, ...`. If no gene qualifies the result has zero rows and the same columns and types.

## Rules

- Stop with an error if `contrast_level` or `reference_level` is not a value of `condition`, if
  they are equal, if `counts` contains negative or non-integer values, or if a column of `counts`
  has no matching row in `coldata`.
- Do not modify `counts` or `coldata`.

The file will be sourced into a fresh R session and `differential_expression` called on data you
have not seen.
