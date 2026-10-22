test_that("module UI is namespaced", {
  html <- as.character(subject$threshold_ui("alpha"))
  expect_match(html,'id="alpha-cutoff"',fixed=TRUE)
  expect_match(html,'id="alpha-summary"',fixed=TRUE)
})
test_that("cutoff and finite values", {
  shiny::testServer(subject$threshold_server,args=list(values=shiny::reactive(c(1,4,NA,Inf,-2))),{
    session$setInputs(cutoff=2); testthat::expect_identical(session$returned(),4)
    session$setInputs(cutoff=-3); testthat::expect_identical(session$returned(),3)
  })
})
test_that("data changes and empty", {
  rv <- shiny::reactiveVal(c(1,2))
  shiny::testServer(subject$threshold_server,args=list(values=rv),{
    session$setInputs(cutoff=0); testthat::expect_equal(session$returned(),3)
    rv(double()); session$flushReact(); testthat::expect_identical(session$returned(),0)
  })
})
test_that("independent module sessions", {
  for (cutoff in c(0,5)) {
    shiny::testServer(subject$threshold_server,args=list(values=shiny::reactive(c(1,3))),{
      session$setInputs(cutoff=cutoff)
      testthat::expect_equal(session$returned(),if(cutoff==0) 4 else 0)
    })
  }
})
