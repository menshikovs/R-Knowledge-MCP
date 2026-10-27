test_that("the task picker adds multiple task IDs before returning", {
  h <- new_pilot()
  on.exit(h$pilot$stop())
  h$pilot$press("f2")
  expect_match(paste(h$pilot$screen_text(), collapse = "\n"), "Select task IDs")
  expect_match(paste(h$pilot$screen_text(), collapse = "\n"), "Selected task IDs: R01")

  picker <- h$app$query_one("#task_picker")
  picker$set(value = "C01")
  h$pilot$press("enter")
  expect_equal(h$session$pane, "task_picker")
  expect_match(paste(h$pilot$screen_text(), collapse = "\n"), "Selected task IDs: R01, C01")

  picker$set(value = "D01")
  h$pilot$press("enter")
  expect_equal(h$session$pane, "task_picker")
  expect_match(paste(h$pilot$screen_text(), collapse = "\n"), "Selected task IDs: R01, C01, D01")

  h$pilot$press("escape")
  expect_equal(h$session$pane, "config")
  expect_equal(h$app$query_one("#tasks")$value, "R01 C01 D01")
})
