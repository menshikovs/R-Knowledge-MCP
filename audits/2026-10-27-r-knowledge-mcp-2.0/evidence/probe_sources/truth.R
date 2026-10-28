pkgs <- c("MASS","lattice","cluster","rpart","boot","nnet","class","codetools","foreign","KernSmooth","nlme","Matrix","survival","mgcv")
out <- commandArgs(TRUE)[1]
for (p in pkgs) {
  ver <- as.character(packageVersion(p))
  ex <- sort(getNamespaceExports(p))
  db <- tools::Rd_db(p)
  al <- sort(unique(unlist(lapply(db, function(rd) tools:::.Rd_get_metadata(rd, "alias")))))
  nsinfo <- parseNamespaceFile(p, .libPaths()[1], mustExist=FALSE)
  s3 <- nsinfo$S3methods
  writeLines(c(paste0("V\t", ver), paste0("E\t", ex), paste0("A\t", al), paste0("S3\t", length(unique(paste(s3[,1], s3[,2]))))), file.path(out, paste0(p, ".txt")))
  cat(p, ver, length(ex), length(al), "\n")
}
