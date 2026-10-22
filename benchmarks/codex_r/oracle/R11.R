test_that("overlap adjacency and chromosome separation", {
  y <- subject$summarize_ranges(data.frame(chr=c("b","a","a","a"),start=c(2L,1L,3L,6L),end=c(2L,3L,5L,8L)))
  expect_equal(as.data.frame(y),data.frame(chr=c("a","b"),bases=c(8L,1L),segments=c(1L,1L)))
})
test_that("disjoint single points and duplication", {
  y <- subject$summarize_ranges(data.frame(chr="x",start=c(1L,1L,4L),end=c(1L,1L,4L)))
  expect_identical(y$bases,2L); expect_identical(y$segments,2L)
})
test_that("typed empty and pinned API", {
  expect_identical(as.character(packageVersion("IRanges")),"2.44.0")
  y <- subject$summarize_ranges(data.frame(chr=character(),start=integer(),end=integer()))
  expect_identical(y$chr,character()); expect_identical(y$bases,integer()); expect_identical(y$segments,integer())
})
test_that("invalid biological coordinates rejected", {
  for (pair in list(c(0L,2L),c(4L,2L),c(NA_integer_,2L),c(1.5,3))) {
    expect_error(subject$summarize_ranges(data.frame(chr="x",start=pair[1],end=pair[2])))
  }
  expect_error(subject$summarize_ranges(data.frame(chr=NA_character_,start=1L,end=2L)))
})
