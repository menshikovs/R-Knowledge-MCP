# Public sample fixture for XP02 (candidate-visible): the Imports field of a few installed packages.
ip <- installed.packages()
pk <- c("clipr", "cli", "glue", "tibble", "R6")
d <- data.frame(package = pk, version = ip[pk, "Version"], imports = unname(ip[pk, "Imports"]))
d$imports <- gsub("\\s+", " ", d$imports)
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "imports_sample.csv"), row.names = FALSE, na = "")
