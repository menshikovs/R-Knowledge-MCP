test_that("cleaning deduplication and order", {
  x <- data.frame(id=c(" b ", "a", "a", "", NA, "c", "b"), value=c(2, 1, 9, 5, 7, NA, 8))
  y <- subject$clean_records(x)
  expect_equal(y, data.frame(id=c("a","b"), value=c(1,2)), ignore_attr=TRUE)
})
test_that("typed empty and nonfinite input", {
  y <- subject$clean_records(data.frame(id=c("x","y"), value=c(Inf,NaN)))
  expect_identical(names(y), c("id","value"))
  expect_identical(y$id, character()); expect_identical(y$value, double())
})
test_that("first valid duplicate and no input mutation", {
  x <- data.frame(id=c("a","a","a"), value=c(NA,4,2)); before <- x
  y <- subject$clean_records(x)
  expect_equal(y$value,4); expect_identical(x,before)
})
test_that("invalid schema rejected", {
  expect_error(subject$clean_records(data.frame(id="a")))
  expect_error(subject$clean_records(data.frame(id=1L,value=2)))
  expect_error(subject$clean_records(data.frame(id="a",value="2")))
})
