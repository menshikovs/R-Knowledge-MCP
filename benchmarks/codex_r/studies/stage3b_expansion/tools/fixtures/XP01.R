# Public sample fixture for XP01 (candidate-visible): metadata of a few installed packages, taken
# from the pinned library of the scorer image.
ip <- installed.packages(fields = c("LinkingTo"))
pk <- c("R6", "cli", "tibble", "dplyr")
d <- data.frame(package = pk, version = ip[pk, "Version"], depends = unname(ip[pk, "Depends"]),
                imports = unname(ip[pk, "Imports"]), linking_to = unname(ip[pk, "LinkingTo"]))
d[] <- lapply(d, function(z) gsub("\\s+", " ", z))
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "deps_sample.csv"), row.names = FALSE, na = "")
