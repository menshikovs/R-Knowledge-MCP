test_that("grouped sums include zero and negative totals", {
  x <- data.frame(team=c("B"," A ","A","B",NA,"C"), amount=c(2,-2,2,9,8,3),
                  active=c(TRUE,TRUE,TRUE,FALSE,TRUE,NA))
  y <- subject$summarize_sales(x)
  expect_equal(as.data.frame(y),data.frame(team=c("A","B"), total=c(0,2),n=c(2L,1L)))
})
test_that("factor identifiers and filtering", {
  x <- data.frame(team=factor(c("x","y","", "x")),amount=c(NA,Inf,3,4),active=TRUE)
  y <- subject$summarize_sales(x)
  expect_identical(y$team,"x"); expect_identical(y$total,4); expect_identical(y$n,1L)
})
test_that("typed empty result", {
  y <- subject$summarize_sales(data.frame(team=character(),amount=double(),active=logical()))
  expect_identical(y$team,character()); expect_identical(y$total,double())
  expect_identical(y$n,integer())
})
test_that("ungrouped and input preserved", {
  x <- data.frame(team=c("z","a"),amount=c(1,2),active=TRUE); before <- x
  y <- subject$summarize_sales(x)
  expect_false(inherits(y,"grouped_df")); expect_identical(x,before)
  expect_identical(names(y),c("team","total","n"))
})
