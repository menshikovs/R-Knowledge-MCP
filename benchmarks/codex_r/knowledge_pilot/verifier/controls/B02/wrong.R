carry_device_state <- function(events) {
  tidyr::fill(events, state, .direction="updown")
}
