test_that("threshold and group react", {
  shiny::testServer(subject$make_filter_server(shiny::reactive(data.frame(group=c("A","B","A"),value=c(1,4,8)))),{
    session$setInputs(minimum=3,group="A")
    testthat::expect_identical(filtered()$value,8); testthat::expect_identical(total(),8)
    session$setInputs(group="all"); testthat::expect_equal(total(),12)
  })
})
test_that("data invalidates reactives", {
  rv <- shiny::reactiveVal(data.frame(group="A",value=2))
  shiny::testServer(subject$make_filter_server(rv),{
    session$setInputs(minimum=0,group="all"); testthat::expect_equal(total(),2)
    rv(data.frame(group="B",value=9)); session$flushReact()
    testthat::expect_equal(total(),9)
  })
})
test_that("nonfinite missing group and empty", {
  shiny::testServer(subject$make_filter_server(shiny::reactive(data.frame(group=c("A","B",NA,"A"),value=c(NA,Inf,3,-2)))),{
    session$setInputs(minimum=0,group="all")
    testthat::expect_equal(nrow(filtered()),0L); testthat::expect_identical(total(),0)
  })
})
test_that("defaults and row order", {
  shiny::testServer(subject$make_filter_server(shiny::reactive(data.frame(group=c("B","A","A"),value=c(2,-1,4)))),{
    session$flushReact(); testthat::expect_equal(filtered()$value,c(2,4))
    testthat::expect_identical(total(),6)
  })
})
