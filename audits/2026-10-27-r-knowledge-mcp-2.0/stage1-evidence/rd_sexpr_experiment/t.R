d <- Sys.getenv("RDEXP")
for (f in c("top.Rd","nested.Rd")) {
  rd <- tools:::prepare_Rd(file.path(d, f), stages = "build")
  al <- tools:::.Rd_get_metadata(rd, "alias")
  cat(f, "aliases after build stage:", paste(al, collapse=","), "\n")
}
