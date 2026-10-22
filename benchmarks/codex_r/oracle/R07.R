test_that("date boundaries nulls and left join", {
  con <- revenue_db(); on.exit(DBI::dbDisconnect(con))
  y <- subject$revenue_by_region(con,"2025-01-01","2025-02-01")
  expect_equal(as.data.frame(y),data.frame(region=c("A","B","Unknown"),revenue=c(10,0,7),orders=c(1L,1L,2L)))
})
test_that("untrusted boundaries do not alter SQL", {
  con <- revenue_db(); on.exit(DBI::dbDisconnect(con))
  y <- subject$revenue_by_region(con,"x' OR 1=1 --","z")
  expect_equal(nrow(y),0L)
})
test_that("caller connection and tables preserved", {
  con <- revenue_db(); on.exit(DBI::dbDisconnect(con))
  before <- DBI::dbReadTable(con,"orders")
  subject$revenue_by_region(con,"2025-01-01","2025-02-01")
  expect_true(DBI::dbIsValid(con)); expect_identical(DBI::dbReadTable(con,"orders"),before)
})
test_that("empty result schema and stable ordering", {
  con <- revenue_db(); on.exit(DBI::dbDisconnect(con))
  y <- subject$revenue_by_region(con,"1900-01-01","1901-01-01")
  expect_identical(names(y),c("region","revenue","orders"))
  expect_identical(y$region,character()); expect_identical(y$revenue,double())
  expect_identical(y$orders,integer())
})
