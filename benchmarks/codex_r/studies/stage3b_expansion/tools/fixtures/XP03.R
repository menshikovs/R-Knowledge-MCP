# Public sample fixture for XP03 (candidate-visible): the stated R requirement of a few packages.
ip <- installed.packages()
pk <- c("R6", "cli", "survival", "Matrix", "purrr")
d <- data.frame(package = pk, version = ip[pk, "Version"], depends = gsub("\\s+", " ", unname(ip[pk, "Depends"])))
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "r_requirements_sample.csv"), row.names = FALSE, na = "")
