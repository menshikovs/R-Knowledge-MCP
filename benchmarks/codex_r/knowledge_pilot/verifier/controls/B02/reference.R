carry_device_state <- function(events) {
  events |>
    dplyr::mutate(.row=seq_len(dplyr::n()), state_filled=state) |>
    dplyr::group_by(device, batch) |>
    dplyr::arrange(.row, .by_group=TRUE) |>
    tidyr::fill(state_filled, .direction="down") |>
    dplyr::ungroup() |>
    dplyr::arrange(.row) |>
    dplyr::select(-.row)
}
