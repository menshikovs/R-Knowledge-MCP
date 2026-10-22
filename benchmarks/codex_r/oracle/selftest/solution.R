# Oracle self-tests only. NEVER export or mount in a candidate session.
clean_records <- function(data) {
  stopifnot(is.data.frame(data),all(c("id","value") %in% names(data)),is.character(data$id),is.numeric(data$value))
  out <- data.frame(id=trimws(data$id),value=as.double(data$value))
  out <- out[!is.na(out$id)&nzchar(out$id)&is.finite(out$value),,drop=FALSE]
  out <- out[!duplicated(out$id),,drop=FALSE]
  out <- out[order(out$id),,drop=FALSE]; rownames(out) <- NULL; out
}
summarize_sales <- function(data) {
  dplyr::summarise(dplyr::group_by(dplyr::filter(
    dplyr::mutate(data,team=trimws(as.character(.data$team))),
    .data$active %in% TRUE,!is.na(.data$team),nzchar(.data$team),is.finite(.data$amount)),
    .data$team),total=as.double(sum(.data$amount)),n=as.integer(dplyr::n()),.groups="drop") |>
    dplyr::arrange(.data$team)
}
import_measurements <- function(path) {
  d <- readr::read_csv(path,col_types=readr::cols(id=readr::col_integer(),
       reading=readr::col_double(),group=readr::col_character()),na=c("","NA"),
       show_col_types=FALSE,progress=FALSE)
  list(data=d,problems=readr::problems(d))
}
plot_measurements <- function(data) {
  d <- data[is.finite(data$time)&is.finite(data$signal)&data$signal>0&!is.na(data$group),,drop=FALSE]
  ggplot2::ggplot(d,ggplot2::aes(x=.data$time,y=.data$signal,colour=.data$group,group=.data$group))+
    ggplot2::geom_point()+ggplot2::geom_line()+ggplot2::scale_y_log10()
}
pivot_visits <- function(data) {
  stopifnot(!anyNA(data$id),!anyDuplicated(data$id))
  out <- tidyr::pivot_longer(data,-"id",names_to=c(".value","week"),names_pattern="(score|flag)_w([12])",
                             names_transform=list(week=as.integer))
  out$score <- as.double(out$score); out$id <- as.character(out$id)
  dplyr::arrange(out,.data$id,.data$week)
}
lookup_accounts <- function(db_path,owner,min_balance) {
  stopifnot(is.numeric(min_balance),length(min_balance)==1,is.finite(min_balance))
  con <- DBI::dbConnect(RSQLite::SQLite(),db_path); on.exit(DBI::dbDisconnect(con))
  out <- DBI::dbGetQuery(con,"SELECT id, owner, balance FROM accounts WHERE owner = ? AND balance >= ? ORDER BY id",
                        params=list(owner,min_balance))
  out$id <- as.integer(out$id); out$balance <- as.double(out$balance); out
}
revenue_by_region <- function(con,from_date,to_date) {
  out <- DBI::dbGetQuery(con,paste(
    "SELECT COALESCE(c.region, 'Unknown') AS region,",
    "SUM(COALESCE(o.amount, 0)) AS revenue, COUNT(*) AS orders",
    "FROM orders o LEFT JOIN customers c ON o.customer_id=c.id",
    "WHERE o.order_date >= ? AND o.order_date < ?",
    "GROUP BY COALESCE(c.region, 'Unknown') ORDER BY region"),params=list(from_date,to_date))
  out$region <- as.character(out$region)
  out$revenue <- as.double(out$revenue); out$orders <- as.integer(out$orders); out
}
make_filter_server <- function(data) {
  force(data)
  function(input,output,session) {
  filtered <- shiny::reactive({
    d <- data(); minimum <- if(is.null(input$minimum)) 0 else input$minimum
    group <- if(is.null(input$group)) "all" else input$group
    ok <- is.finite(d$value)&d$value>=minimum&!is.na(d$group)
    if(group!="all") ok <- ok&d$group==group
    d[ok,,drop=FALSE]
  })
  total <- shiny::reactive(as.double(sum(filtered()$value)))
  }
}
threshold_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(shiny::numericInput(ns("cutoff"),"Cutoff",0),shiny::textOutput(ns("summary")))
}
threshold_server <- function(id,values) {
  shiny::moduleServer(id,function(input,output,session) {
    result <- shiny::reactive({
      cutoff <- if(is.null(input$cutoff)) 0 else input$cutoff
      x <- values(); as.double(sum(x[is.finite(x)&x>=cutoff]))
    })
    output$summary <- shiny::renderText(result())
    result
  })
}
summarize_ranges <- function(data) {
  stopifnot(is.character(data$chr),!anyNA(data$chr),all(nzchar(trimws(data$chr))),
            is.numeric(data$start),is.numeric(data$end),
            all(is.finite(data$start)),all(is.finite(data$end)),
            all(data$start==as.integer(data$start)),all(data$end==as.integer(data$end)),
            all(data$start>=1),all(data$end>=data$start))
  out <- data.frame(chr=character(),bases=integer(),segments=integer())
  for (chr in sort(unique(data$chr))) {
    x <- data[data$chr==chr,,drop=FALSE]
    r <- IRanges::reduce(IRanges::IRanges(start=x$start,end=x$end))
    out <- rbind(out,data.frame(chr=chr,bases=as.integer(sum(IRanges::width(r))),segments=as.integer(length(r))))
  }
  out
}
build_report <- function(csv_path,output_dir) {
  d <- readr::read_csv(csv_path,col_types=readr::cols(id=readr::col_character(),
    group=readr::col_character(),x=readr::col_double(),y=readr::col_double()),
    show_col_types=FALSE,progress=FALSE)
  stopifnot(all(c("id","group","x","y") %in% names(d)))
  d$id <- trimws(d$id); d$group <- trimws(d$group)
  d <- d[!is.na(d$id)&nzchar(d$id)&!is.na(d$group)&nzchar(d$group)&is.finite(d$x)&is.finite(d$y)&d$y>0,,drop=FALSE]
  d <- d[!duplicated(d$id),,drop=FALSE]; d <- dplyr::arrange(d,.data$id)
  summary <- dplyr::summarise(dplyr::group_by(d,.data$group),n=as.integer(dplyr::n()),
                              mean_y=as.double(mean(.data$y)),.groups="drop")
  summary <- dplyr::arrange(summary,.data$group)
  p <- ggplot2::ggplot(d,ggplot2::aes(x=.data$x,y=.data$y,colour=.data$group))+ggplot2::geom_point()
  dir.create(output_dir,recursive=TRUE,showWarnings=FALSE)
  write.csv(summary,file.path(output_dir,"summary.csv"),row.names=FALSE)
  saveRDS(p,file.path(output_dir,"plot.rds"))
  report <- file.path(output_dir,"report.qmd")
  writeLines(c("---","title: Workflow","format: html","---","","# Summary","",
    "\x60\x60\x60{r}","knitr::kable(read.csv('summary.csv'))","readRDS('plot.rds')","\x60\x60\x60"),report)
  list(data=d,summary=summary,plot=p,report=report)
}
