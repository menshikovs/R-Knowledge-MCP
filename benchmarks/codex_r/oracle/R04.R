test_that("object and intended mappings", {
  p <- subject$plot_measurements(data.frame(time=c(1,2,1,2),signal=c(10,100,5,50),group=c("A","A","B","B")))
  expect_s3_class(p,"ggplot")
  built <- ggplot2::ggplot_build(p)
  expect_equal(sort(built$data[[1]]$x),c(1,1,2,2))
  expect_equal(sort(built$data[[1]]$y),sort(log10(c(10,100,5,50))))
})
test_that("points lines and separate line groups", {
  p <- subject$plot_measurements(data.frame(time=c(1,2,1,2),signal=c(2,3,4,5),group=c("A","A","B","B")))
  expect_true(any(vapply(p$layers,function(l) inherits(l$geom,"GeomPoint"),logical(1))))
  idx <- which(vapply(p$layers,function(l) inherits(l$geom,"GeomLine"),logical(1)))[1]
  expect_false(is.na(idx)); b <- ggplot2::ggplot_build(p)$data[[idx]]
  expect_equal(length(unique(b$group)),2L); expect_equal(length(unique(b$colour)),2L)
})
test_that("invalid rows excluded before plotting", {
  p <- subject$plot_measurements(data.frame(time=c(1,2,3,Inf,4),signal=c(2,0,-1,3,NA),group="A"))
  expect_equal(nrow(ggplot2::ggplot_build(p)$data[[1]]),1L)
})
test_that("typed empty and NA group supported", {
  p <- subject$plot_measurements(data.frame(time=double(),signal=double(),group=character()))
  expect_s3_class(p,"ggplot"); expect_equal(nrow(ggplot2::ggplot_build(p)$data[[1]]),0L)
  p <- subject$plot_measurements(data.frame(time=1,signal=2,group=NA_character_))
  expect_equal(nrow(ggplot2::ggplot_build(p)$data[[1]]),0L)
})
