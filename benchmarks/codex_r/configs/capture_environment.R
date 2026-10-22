# Development-only inventory. No packages are downloaded or installed.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 1L)
lib <- Sys.getenv("BENCH_R_LIBRARY")
if (nzchar(lib)) .libPaths(c(lib, .libPaths()))
roots <- c("dplyr", "readr", "ggplot2", "tidyr", "DBI", "RSQLite", "shiny",
           "knitr", "rmarkdown", "testthat", "jsonlite", "xml2", "renv", "IRanges")
stopifnot(all(roots %in% rownames(installed.packages())))
lock <- renv::lockfile_create(packages = roots, libpaths = .libPaths(), project = tempdir())
lock$Bioconductor <- list(Version = "3.22")
# Keep canonical restoration fields, not locale-sensitive descriptive metadata.
keys <- c("Package", "Version", "Source", "Repository", "Hash", "Requirements")
lock$Packages <- lapply(lock$Packages,function(record) unclass(record)[intersect(keys,names(record))])
jsonlite::write_json(unclass(lock),args[[1L]],auto_unbox=TRUE,pretty=TRUE,null="null")
cat("Lock written with", length(lock$Packages), "package records\n")
