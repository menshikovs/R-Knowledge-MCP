#### control: reference
# Trusted reference: tidy evaluation with the .data pronoun.
top_by <- function(data, group, rank, n = 1L) {
  if (!is.numeric(n) || length(n) != 1L || is.na(n) || n < 1 || n != round(n)) stop("bad n")
  d <- data
  d$.i <- seq_len(nrow(d))
  d <- d[!is.na(d[[group]]) & !is.na(d[[rank]]), , drop = FALSE]
  out <- d |>
    dplyr::group_by(.data[[group]]) |>
    dplyr::arrange(dplyr::desc(.data[[rank]]), .data$.i, .by_group = TRUE) |>
    dplyr::slice_head(n = n) |>
    dplyr::ungroup() |>
    as.data.frame()
  out <- out[order(as.character(out[[group]]), -out[[rank]], out$.i), ]
  out$.i <- NULL
  rownames(out) <- NULL
  out
}

#### control: alternate_base_r
# Alternate valid solution: base R only.
top_by <- function(data, group, rank, n = 1L) {
  stopifnot(is.numeric(n), length(n) == 1, !is.na(n), n >= 1, n == round(n))
  i <- which(!is.na(data[[group]]) & !is.na(data[[rank]]))
  i <- i[order(as.character(data[[group]][i]), -data[[rank]][i], i)]
  k <- ave(seq_along(i), as.character(data[[group]][i]), FUN = seq_along)
  out <- data[i[k <= n], , drop = FALSE]
  rownames(out) <- NULL
  out
}

#### control: wrong_underscore_verbs_unchanged
# The legacy code as delivered: defunct functions raise an error.
top_by <- function(data, group, rank, n = 1L) {
  data |>
    dplyr::group_by_(group) |>
    dplyr::arrange_(paste0("desc(", rank, ")")) |>
    dplyr::filter_(paste0("row_number() <= ", n)) |>
    dplyr::ungroup()
}

#### control: wrong_top_n_keeps_ties
# Plausible wrong strategy: dplyr::top_n() keeps all tied rows.
top_by <- function(data, group, rank, n = 1L) {
  if (!is.numeric(n) || length(n) != 1L || is.na(n) || n < 1 || n != round(n)) stop("bad n")
  d <- data[!is.na(data[[group]]) & !is.na(data[[rank]]), ]
  out <- d |> dplyr::group_by(.data[[group]]) |> dplyr::top_n(n, .data[[rank]]) |> dplyr::ungroup()
  out <- as.data.frame(out)
  out <- out[order(as.character(out[[group]]), -out[[rank]]), ]
  rownames(out) <- NULL
  out
}

#### control: wrong_ascending_order
# Plausible wrong strategy: smallest values instead of largest.
top_by <- function(data, group, rank, n = 1L) {
  if (!is.numeric(n) || length(n) != 1L || is.na(n) || n < 1 || n != round(n)) stop("bad n")
  d <- data[!is.na(data[[group]]) & !is.na(data[[rank]]), ]
  out <- d |> dplyr::group_by(.data[[group]]) |> dplyr::arrange(.data[[rank]], .by_group = TRUE) |>
    dplyr::slice_head(n = n) |> dplyr::ungroup()
  as.data.frame(out)
}

#### control: wrong_keeps_missing_groups
# Plausible wrong strategy: rows with a missing group form their own group and are kept.
top_by <- function(data, group, rank, n = 1L) {
  if (!is.numeric(n) || length(n) != 1L || is.na(n) || n < 1 || n != round(n)) stop("bad n")
  d <- data[!is.na(data[[rank]]), ]
  out <- d |> dplyr::group_by(.data[[group]]) |> dplyr::arrange(dplyr::desc(.data[[rank]]), .by_group = TRUE) |>
    dplyr::slice_head(n = n) |> dplyr::ungroup()
  as.data.frame(out)
}

#### control: wrong_data_masking_name_clash
# Plausible wrong strategy: passes the argument names straight to dplyr, so `group` and `rank` are
# looked up as columns first (a column named like the argument wins) and as the string otherwise.
top_by <- function(data, group, rank, n = 1L) {
  if (!is.numeric(n) || length(n) != 1L || is.na(n) || n < 1 || n != round(n)) stop("bad n")
  d <- data[!is.na(data[[group]]) & !is.na(data[[rank]]), ]
  out <- d |> dplyr::group_by(group) |> dplyr::arrange(dplyr::desc(rank), .by_group = TRUE) |>
    dplyr::slice_head(n = n) |> dplyr::ungroup()
  as.data.frame(out)
}

#### control: edge_no_n_validation
# Boundary case: right for valid n but never validates it (expected: not fully correct).
# expect: fail
top_by <- function(data, group, rank, n = 1L) {
  i <- which(!is.na(data[[group]]) & !is.na(data[[rank]]))
  i <- i[order(as.character(data[[group]][i]), -data[[rank]][i], i)]
  k <- ave(seq_along(i), as.character(data[[group]][i]), FUN = seq_along)
  out <- data[i[k <= n], , drop = FALSE]
  rownames(out) <- NULL
  out
}

#### control: malformed_returns_vector
# Malformed submission: only the winning values.
# expect: fail
top_by <- function(data, group, rank, n = 1L) tapply(data[[rank]], data[[group]], max, na.rm = TRUE)

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
top_by <- function(data, group, rank, n = 1L) stop("todo")
