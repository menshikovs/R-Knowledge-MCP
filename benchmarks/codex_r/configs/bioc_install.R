# Build-time only. Installs the exact E02/E03 pins without upgrading any locked package.
stopifnot(as.character(getRversion()) == "4.5.2")
lib <- "/opt/benchmark-library"
.libPaths(c(lib, .libPaths()))
options(repos = c(CRAN = "https://cloud.r-project.org"), timeout = 600, Ncpus = 4L)
Sys.setenv(MAKEFLAGS = "-j4")
pins <- c(DESeq2 = "1.50.2", SummarizedExperiment = "1.40.0", Biobase = "2.70.0",
          GenomicRanges = "1.62.0")
before <- vapply(rownames(installed.packages(lib.loc = lib)), function(p)
  as.character(packageVersion(p, lib.loc = lib)), character(1L))
BiocManager::install(names(pins), version = "3.22", lib = lib, update = FALSE, ask = FALSE)
# Bioconductor 3.22 now serves GenomicRanges 1.62.1; the E03 pin is 1.62.0, which stays
# available in the release's Archive. Install that exact tarball, verified by SHA-256.
archive_url <- "https://bioconductor.org/packages/3.22/bioc/src/contrib/Archive/GenomicRanges/GenomicRanges_1.62.0.tar.gz"
archive_sha256 <- "7bc77ad566b4effb93107a520dd3e4395beb5be1fab3c70e085390c212a14b73"
tarball <- file.path(tempdir(), "GenomicRanges_1.62.0.tar.gz")
download.file(archive_url, tarball, mode = "wb", quiet = TRUE)
actual <- strsplit(system2("sha256sum", tarball, stdout = TRUE), " ", fixed = TRUE)[[1L]][[1L]]
if (!identical(actual, archive_sha256)) stop("GenomicRanges 1.62.0 archive hash differs")
install.packages(tarball, repos = NULL, type = "source", lib = lib)
for (p in names(pins)) {
  got <- as.character(packageVersion(p, lib.loc = lib))
  cat(sprintf("%s installed %s pinned %s
", p, got, pins[[p]]))
  if (got != pins[[p]]) stop(sprintf("%s: Bioconductor 3.22 serves %s, task pins %s", p, got, pins[[p]]))
}
lock <- jsonlite::fromJSON("/config/renv.lock", simplifyVector = FALSE)
changed <- Filter(function(r) packageVersion(r$Package, lib.loc = lib) != package_version(r$Version), lock$Packages)
if (length(changed)) {
  stop("locked packages changed: ", paste(vapply(changed, function(r) sprintf("%s lock %s now %s", r$Package, r$Version, as.character(packageVersion(r$Package, lib.loc = lib))), ""), collapse = "; "))
}
stopifnot(identical(before, vapply(names(before), function(p)
  as.character(packageVersion(p, lib.loc = lib)), character(1L))))
