events <- utils::read.csv("/candidate/data/device_events.csv", stringsAsFactors=FALSE, na.strings="NA")
expected <- c("ready", "ready", NA, NA, "alarm", "ready")
check("output preserves input and adds result", {
  z <- call_candidate("carry_device_state", events)
  out <- value_of(z)
  identical(names(out), c(names(events), "state_filled")) && nrow(out) == nrow(events)
})
check("forward fill only", {
  out <- value_of(call_candidate("carry_device_state", events))
  identical(out$state_filled, expected)
})
check("does not mutate input", {
  z <- call_candidate("carry_device_state", events)
  isTRUE(all.equal(z$args_after[[1L]], events))
})
check("preserves original row order and identifiers", {
  out <- value_of(call_candidate("carry_device_state", events))
  identical(out$event_id, events$event_id) && identical(out$device, events$device) &&
    identical(out$batch, events$batch)
})
check("empty input keeps output schema", {
  out <- value_of(call_candidate("carry_device_state", events[FALSE, ]))
  nrow(out) == 0L && identical(names(out), c(names(events), "state_filled"))
})
