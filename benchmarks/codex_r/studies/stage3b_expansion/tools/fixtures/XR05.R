# Public sample fixture for XR05 (candidate-visible): parameter values used by the harness.
g <- data.frame(parameter = c("scale", "scale", "scale", "shift", "shift", "label", "label"),
                value = c("1", "2", "5", "0.5", "-1", "alpha", "beta"))
write.csv(g, file.path(Sys.getenv("OUT_DIR", "/out"), "grid.csv"), row.names = FALSE)
