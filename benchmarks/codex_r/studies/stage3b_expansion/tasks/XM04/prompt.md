# XM04: Transcript-to-gene SummarizedExperiment with sequence checksum verification and sample alignment

In RNA-seq pipelines (such as Salmon + `tximport`/`tximeta`), transcript-level quantifications are
summarized to the gene level and packaged into a Bioconductor `SummarizedExperiment` together with
verified reference-transcriptome provenance and sample metadata. A sample dataset is in
`data/tx_counts.csv`, `data/tx_tpm.csv`, `data/tx_efflen.csv`, `data/coldata.csv`, and
`data/tx_manifest.csv`.

Use only the packages installed in the supplied Bioconductor environment (`SummarizedExperiment`,
`S4Vectors`, `digest`); do not install anything. Write `solution.R` defining
`summarize_transcriptome(counts, tpm, eff_len, coldata, tx_manifest)`.

## Inputs

- `counts`, `tpm`, `eff_len`: numeric matrices with transcript IDs as row names and sample IDs as
  column names.
- `coldata`: a `data.frame` whose **row names are sample IDs** (not necessarily in the same order
  as `colnames(counts)`).
- `tx_manifest`: a `data.frame` with character columns `tx_id`, `gene_id`, `biotype`, `sequence`,
  and `seq_md5` (in no particular row order; may also contain extra reference transcripts not
  present in `counts`).

## Step 1: Validation and transcriptome checksum verification

Stop with an error if any of the following fails:
1. `counts`, `tpm`, and `eff_len` must all be numeric matrices with at least 1 row and 1 column,
   identical dimensions, identical row names (`tx_id`) and column names (`sample_id`) in the same
   order, no missing values (`NA`), no duplicate row or column names, `counts >= 0`, `tpm >= 0`, and
   strictly positive `eff_len > 0`.
2. Every column name of `counts` must exist in `rownames(coldata)`.
3. `tx_manifest` must have no duplicate `tx_id`, and every transcript in `rownames(counts)` must
   appear in `tx_manifest$tx_id`.
4. **Sequence checksum check:** For every quantified transcript (those in `rownames(counts)`), the
   MD5 hash of its `sequence` string—computed with
   `digest::digest(seq_str, algo = "md5", serialize = FALSE)`—must equal its `seq_md5` in
   `tx_manifest`.
5. Within each `gene_id` among the quantified transcripts, all transcripts must share a single
   consistent `biotype` value.

## Step 2: Gene-level summarization

Order the target genes by `sort(unique(gene_id))` (over the quantified transcripts) and keep samples
in the exact order of `colnames(counts)`. For each gene $g$ and sample $s$, aggregate over the
quantified transcripts $t \in g$:

1. **`counts` assay:** $\sum_{t \in g} \text{counts}_{t,s}$
2. **`abundance` assay:** $\sum_{t \in g} \text{tpm}_{t,s}$
3. **`length` assay:** the `tpm`-weighted mean of effective lengths,
   $$\frac{\sum_{t \in g} \text{eff\_len}_{t,s}\,\text{tpm}_{t,s}}{\sum_{t \in g} \text{tpm}_{t,s}},$$
   or, if $\sum_{t \in g} \text{tpm}_{t,s} = 0$ for that $(g, s)$ cell, the unweighted arithmetic
   mean $\frac{1}{|g|}\sum_{t \in g} \text{eff\_len}_{t,s}$.

All three assays must be numeric matrices with row names equal to the sorted `gene_id`s and column
names equal to `colnames(counts)`.

## Step 3: Assemble the `SummarizedExperiment`

Construct and return a `SummarizedExperiment::SummarizedExperiment` object with:
- **`assays`:** named `"counts"`, `"abundance"`, and `"length"` in that exact order.
- **`rowData`:** columns `gene_id` (character), `biotype` (character), and `n_transcripts` (integer:
  number of quantified transcripts mapped to that gene), with row names equal to `gene_id`.
- **`colData`:** `coldata` aligned by sample name to `colnames(counts)` (`coldata[colnames(counts), , drop = FALSE]`).
- **`metadata`:** `list(manifest_md5 = ...)` where `manifest_md5` is
  `digest::digest(paste(paste0(tx_id, ":", seq_md5), collapse = "\n"), algo = "md5", serialize = FALSE)`
  computed over the **quantified** transcripts ordered by `sort(rownames(counts))`.

Do not modify the input objects.

