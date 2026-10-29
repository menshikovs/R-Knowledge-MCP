# Public sample fixture for XP04 (candidate-visible): metadata fields of a few installed packages.
ip <- installed.packages(fields = c("Repository", "biocViews"))
pk <- c("stats", "MASS", "dplyr", "S4Vectors", "IRanges", "docopt")
d <- data.frame(package = pk, version = ip[pk, "Version"], priority = unname(ip[pk, "Priority"]),
                repository = unname(ip[pk, "Repository"]), has_bioc_views = !is.na(unname(ip[pk, "biocViews"])))
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "origin_sample.csv"), row.names = FALSE, na = "")
