# Public sample fixture for XP05 (candidate-visible): an example checklist (not the hidden ones).
d <- data.frame(package = c("dplyr", "MASS", "ggplot2", "notAPackage"),
                op = c(">=", ">=", "<", "=="),
                version = c("1.1.0", "7.3-60", "3.0.0", "1.0.0"))
write.csv(d, file.path(Sys.getenv("OUT_DIR", "/out"), "requirements_sample.csv"), row.names = FALSE)
