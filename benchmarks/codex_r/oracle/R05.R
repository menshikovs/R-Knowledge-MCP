test_that("reshape aligns value columns", {
  y <- subject$pivot_visits(visits())
  expect_identical(y$id,c("a","a","b","b")); expect_identical(y$week,c(1L,2L,1L,2L))
  expect_identical(y$score,c(2,3,1,NA_real_))
  expect_identical(y$flag,c(NA,TRUE,TRUE,FALSE))
})
test_that("all missing rows retained", {
  x <- visits()[1,,drop=FALSE]; x$score_w1 <- x$score_w2 <- NA_real_
  x$flag_w1 <- x$flag_w2 <- NA
  y <- subject$pivot_visits(x)
  expect_equal(nrow(y),2L); expect_true(all(is.na(y$score))); expect_true(all(is.na(y$flag)))
})
test_that("typed empty output", {
  y <- subject$pivot_visits(visits()[FALSE,])
  expect_identical(y$id,character()); expect_identical(y$week,integer())
  expect_identical(y$score,double()); expect_identical(y$flag,logical())
})
test_that("invalid identifiers rejected", {
  x <- visits(); x$id <- c("a","a"); expect_error(subject$pivot_visits(x))
  x$id <- c("a",NA); expect_error(subject$pivot_visits(x))
})
