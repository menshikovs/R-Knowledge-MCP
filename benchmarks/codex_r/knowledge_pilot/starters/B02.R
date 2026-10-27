carry_device_state <- function(events) {
  # BUG: fills backward and carries state across different devices/batches.
  tidyr::fill(events, state, .direction = "updown")
}
