# Build-time only: restore before timing any trial. Runtime has no network.
stopifnot(as.character(getRversion())=="4.5.2")
options(repos=c(CRAN="https://cloud.r-project.org"),timeout=300)
lib <- "/opt/benchmark-library"
dir.create(lib,recursive=TRUE,showWarnings=FALSE)
.libPaths(c(lib,.libPaths()))
if (!requireNamespace("renv",quietly=TRUE)) install.packages("renv",lib=lib)
renv::restore(lockfile="/config/renv.lock",library=lib,project="/opt/benchmark-project",prompt=FALSE)
lock <- renv::lockfile_read("/config/renv.lock")
for (record in lock$Packages) stopifnot(packageVersion(record$Package)==package_version(record$Version))
