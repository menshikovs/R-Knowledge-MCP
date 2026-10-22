# Developer-only static check, with no installation or candidate execution.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==1L)
files <- list.files(args[1],pattern="[.]R$",recursive=TRUE,full.names=TRUE)
invisible(lapply(files,parse))
cat("Parsed",length(files),"R files\n")
