csv_file <- function(lines) {
  p <- tempfile(fileext=".csv"); writeLines(lines,p,useBytes=TRUE); p
}
visits <- function() data.frame(id=c("b","a"),score_w1=c(1,2),score_w2=c(NA_real_,3),
                                flag_w1=c(TRUE,NA),flag_w2=c(FALSE,TRUE))
accounts_db <- function() {
  p <- tempfile(fileext=".sqlite")
  con <- DBI::dbConnect(RSQLite::SQLite(),p); on.exit(DBI::dbDisconnect(con))
  DBI::dbWriteTable(con,"accounts",data.frame(id=1:5,owner=c("Alice","Alice","Bob","x' OR 1=1 --","Alice"),
                                            balance=c(10,20,30,5,NA_real_)))
  p
}
capture_connections <- function(operation) {
  .GlobalEnv$.bench_connections <- list()
  suppressMessages(trace("dbConnect",where=asNamespace("DBI"),print=FALSE,
    exit=quote(.GlobalEnv$.bench_connections[[length(.GlobalEnv$.bench_connections)+1L]] <- returnValue())))
  on.exit(suppressMessages(untrace("dbConnect",where=asNamespace("DBI"))))
  operation()
  .GlobalEnv$.bench_connections
}
revenue_db <- function() {
  con <- DBI::dbConnect(RSQLite::SQLite(),":memory:")
  DBI::dbWriteTable(con,"customers",data.frame(id=1:3,region=c("A","B",NA_character_)))
  DBI::dbWriteTable(con,"orders",data.frame(id=1:6,customer_id=c(1L,2L,3L,99L,1L,1L),
    order_date=c("2025-01-01","2025-01-02","2025-01-03","2025-01-04","2025-02-01","2024-12-31"),
    amount=c(10,NA_real_,3,4,100,200)))
  con
}
rev_data <- function(lines) c(lines[1],rev(lines[-1]))
html_table_rows <- function(html) {
  doc <- xml2::read_html(html)
  trimws(gsub("[[:space:]]+"," ",xml2::xml_text(xml2::xml_find_all(doc,"//table//tr"))))
}
render_workflow_report <- function(path) {
  work <- tempfile("render-"); dir.create(work)
  files <- list.files(dirname(path),full.names=TRUE,all.files=FALSE)
  stopifnot(all(file.copy(files,work,recursive=TRUE)))
  old <- setwd(work); on.exit(setwd(old),add=TRUE)
  status <- system2(Sys.which("quarto"),c("render", "report.qmd", "--to", "html", "--output", "report.html"),
                    stdout=TRUE,stderr=TRUE,timeout=45)
  if (!is.null(attr(status,"status")) && attr(status,"status")!=0) stop("Report rendering failed")
  paste(readLines("report.html",warn=FALSE),collapse="\n")
}
render_report <- function(path,lines) {
  work <- tempfile("report-"); dir.create(work); dir.create(file.path(work,"data"))
  file.copy(path,file.path(work,"report.qmd"))
  writeLines(lines,file.path(work,"data","sales.csv"))
  render_workflow_report(file.path(work,"report.qmd"))
}
workflow_result <- function() {
  p <- csv_file(c("id,group,x,y","a,G1,1,2","b,G2,2,4","c,G1,3,6"))
  subject$build_report(p,tempfile("workflow-"))
}
