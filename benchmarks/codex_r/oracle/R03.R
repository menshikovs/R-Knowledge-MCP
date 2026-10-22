test_that("explicit types and malformed rows retained", {
  p <- csv_file(c("id,reading,group","1,2.5,A","bad,oops,B","3,,NA"))
  y <- suppressWarnings(subject$import_measurements(p))
  expect_identical(y$data$id,c(1L,NA_integer_,3L))
  expect_identical(y$data$reading,c(2.5,NA_real_,NA_real_))
  expect_identical(y$data$group,c("A","B",NA_character_))
})
test_that("parser diagnostics retained", {
  p <- csv_file(c("id,reading,group","x,1,A","2,no,B"))
  y <- suppressWarnings(subject$import_measurements(p))
  expect_equal(nrow(y$problems),2L)
  expect_setequal(y$problems$actual,c("x","no"))
})
test_that("empty file with header stays typed", {
  y <- subject$import_measurements(csv_file("id,reading,group"))
  expect_identical(y$data$id,integer()); expect_identical(y$data$reading,double())
  expect_identical(y$data$group,character()); expect_equal(nrow(y$problems),0L)
})
test_that("character labels and missing file", {
  y <- subject$import_measurements(csv_file(c("id,reading,group","01,4,001")))
  expect_identical(y$data$group,"001")
  expect_error(subject$import_measurements(file.path(tempdir(),"does-not-exist-134.csv")))
})
