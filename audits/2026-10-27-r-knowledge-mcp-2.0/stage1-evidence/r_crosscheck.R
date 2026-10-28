# Own script. Parses Rd and NAMESPACE with R's parsers (no package code is run) and prints
# per package: aliases and explicit export names, for comparison with the server's static result.
args <- commandArgs(trailingOnly = TRUE)
root <- args[1]
out <- list()
for (pkg in list.dirs(root, recursive = FALSE, full.names = FALSE)) {
  dir <- file.path(root, pkg)
  rds <- list.files(file.path(dir, "man"), pattern = "[.]Rd$", full.names = TRUE)
  al <- character()
  for (f in rds) {
    rd <- tryCatch(suppressWarnings(tools::parse_Rd(f, permissive = TRUE)), error = function(e) NULL)
    if (!is.null(rd)) al <- c(al, tools:::.Rd_get_metadata(rd, "alias"))
  }
  ns <- tryCatch(parseNamespaceFile(pkg, root, mustExist = FALSE), error = function(e) NULL)
  ex <- if (is.null(ns)) NA_character_ else c(ns$exports, ns$exportClasses, ns$exportMethods)
  pat <- if (is.null(ns)) NA_integer_ else length(ns$exportPatterns)
  m3 <- if (is.null(ns) || !nrow(ns$S3methods)) character() else paste(ns$S3methods[, 1], ns$S3methods[, 2], sep = " ")
  out[[pkg]] <- list(aliases = sort(unique(al)), exports = sort(unique(ex)), patterns = pat, s3 = sort(unique(m3)))
}
con <- file(args[2], "w")
for (pkg in names(out)) {
  o <- out[[pkg]]
  cat(pkg, "\t", length(o$aliases), "\t", length(o$exports), "\t", o$patterns, "\n", file = con, sep = "")
  writeLines(paste0("A\t", pkg, "\t", o$aliases), con)
  writeLines(paste0("E\t", pkg, "\t", o$exports), con)
  writeLines(paste0("M	", pkg, "	", o$s3), con)
}
close(con)
