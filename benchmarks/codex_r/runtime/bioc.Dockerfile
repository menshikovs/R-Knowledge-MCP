# Reuse verified installed R packages only. No scorer files, fixtures, reference
# solutions, harness or /config directory are copied from the library donor.
# Build with --pull=false; record and verify both local source image IDs.
ARG BIOC_LIBRARY_IMAGE=codex-r-benchmark@sha256:a4e959f2ed9af8141ecec5d95d727880fd5dfc325efc19cb55032d6d34899161
ARG EXECUTOR_BASE=rkmcp-codex-runtime@sha256:ea7eaa089df6671c5eb7dc913fb752909dff5344aafe5f8c4974aa97e2365074
FROM ${BIOC_LIBRARY_IMAGE} AS bioc_library
FROM ${EXECUTOR_BASE}
COPY --from=bioc_library /opt/benchmark-library/ /opt/benchmark-library/
RUN Rscript --vanilla -e 'stopifnot(as.character(getRversion()) == "4.5.2"); pins <- c(BiocVersion="3.22.0", DESeq2="1.50.2", SummarizedExperiment="1.40.0", Biobase="2.70.0", GenomicRanges="1.62.0"); stopifnot(all(vapply(names(pins), function(p) as.character(packageVersion(p)), "") == pins))'
# All executor configuration (USER, ENTRYPOINT, CMD, ENV, WORKDIR) is inherited.
