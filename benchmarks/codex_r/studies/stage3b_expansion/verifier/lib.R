# Shared helpers for Stage 3B hidden checks (verifier side). Sourced after the hard-v1 harness.
# Everything that must run inside the candidate session (plot digests, option preludes) is
# self-contained: it travels to the isolated callr session as a closure whose parent is that
# session's global environment, so it cannot rely on anything defined here.

# ---- deterministic withheld variants ---------------------------------------------------------
# Variants are generated from fixed seeds with explicit RNG kinds, so they are identical on every
# run of R 4.5.x; they differ from the public fixture (which uses its own seed).
with_seed <- function(seed, expr) {
  had <- exists(".Random.seed", envir = globalenv(), inherits = FALSE)
  old <- if (had) get(".Random.seed", envir = globalenv(), inherits = FALSE)
  on.exit({
    if (had) assign(".Random.seed", old, envir = globalenv())
    else if (exists(".Random.seed", envir = globalenv(), inherits = FALSE)) {
      rm(".Random.seed", envir = globalenv())
    }
  })
  set.seed(seed, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
  force(expr)
}

expect_close <- function(actual, expected, tol = 1e-8, info = NULL) {
  testthat::expect_equal(unname(as.numeric(actual)), unname(as.numeric(expected)),
                         tolerance = tol, info = info)
}

# Named element of a candidate's list result, with a readable failure instead of NULL propagation.
field <- function(x, name) {
  if (!is.list(x) || is.null(x[[name]])) stop("result has no element '", name, "'")
  x[[name]]
}

# ---- negative expectations must not be vacuous ------------------------------------------------
# An undefined function "raises an error" too. A negative check therefore first proves that the
# function exists and handles a valid call, and then requires an error that comes from the
# function itself rather than from R failing to find it.
expect_stops <- function(result, works) {
  value_of(works)
  if (isTRUE(result$ok)) stop("expected an error but the call succeeded")
  if (any(grepl("could not find function|object .* not found", result$message))) {
    stop("the function is not defined: ", substr(paste(result$message, collapse = " "), 1L, 120L))
  }
  invisible(TRUE)
}

# ---- calling candidate functions with a prelude / digest -------------------------------------
# call_wrapped("make_plot", data, .digest = plot_digest) runs `make_plot(data)` in the candidate
# session and converts the result with `.digest` *inside that session*, returning plain values.
# `.prelude` is an expression evaluated first (e.g. options(lifecycle_verbosity = "warning")); its
# option changes are undone afterwards. Warnings are collected by the harness.
call_wrapped <- function(name, ..., .digest = NULL, .prelude = NULL, .timeout = 60) {
  wrapper <- function(...) {
    if (!is.null(.prelude)) {
      before <- options()
      on.exit(options(before), add = TRUE)
      eval(.prelude, globalenv())
    }
    fn <- get(.name, envir = globalenv(), mode = "function")
    out <- fn(...)
    if (!is.null(.digest)) out <- .digest(out)
    out
  }
  environment(wrapper) <- list2env(
    list(.name = name, .digest = .digest, .prelude = .prelude), parent = globalenv()
  )
  call_candidate(wrapper, ..., .timeout = .timeout)
}

# Fail on any lifecycle deprecation warning raised while the candidate runs.
lifecycle_prelude <- quote(options(lifecycle_verbosity = "warning", rlib_warning_verbosity = "verbose"))

expect_no_lifecycle_warnings <- function(result) {
  bad <- grep("deprecated|defunct|superseded|soft-deprecated", result$warnings, value = TRUE,
              ignore.case = TRUE)
  if (length(bad)) stop("deprecation warning: ", substr(bad[[1]], 1L, 200L))
  invisible(TRUE)
}

# ---- ggplot2 digest (runs in the candidate session) -----------------------------------------
plot_digest <- function(p, max_rows = 5000L) {
  if (!inherits(p, "ggplot")) stop("the function did not return a ggplot object")
  safe <- function(expr, default = NULL) tryCatch(expr, error = function(e) default)
  as_plain <- function(df) {
    df <- as.data.frame(df, stringsAsFactors = FALSE)
    if (nrow(df) > max_rows) df <- df[seq_len(max_rows), , drop = FALSE]
    for (nm in names(df)) {
      col <- df[[nm]]
      if (is.factor(col)) df[[nm]] <- as.character(col)
      else if (inherits(col, "Date")) df[[nm]] <- as.numeric(col)
      else if (is.list(col)) df[[nm]] <- vapply(col, function(z) paste(format(z), collapse = ","), "")
    }
    df
  }
  built <- ggplot2::ggplot_build(p)
  labs <- safe(lapply(ggplot2::get_labs(built), function(l) paste(as.character(l), collapse = " ")), list())
  layers <- lapply(seq_along(p$layers), function(i) {
    ly <- p$layers[[i]]
    list(
      geom = class(ly$geom)[1], stat = class(ly$stat)[1], position = class(ly$position)[1],
      show_legend = safe(ly$show.legend), aes_params = safe(names(ly$aes_params), character()),
      mapping_names = safe(names(ly$mapping), character()),
      stat_params = safe(lapply(ly$stat_params, function(z) if (is.atomic(z) && length(z) < 20) z else class(z)[1])),
      geom_params = safe(lapply(ly$geom_params, function(z) if (is.atomic(z) && length(z) < 20) z else class(z)[1])),
      data = as_plain(built$data[[i]]),
      # Mapped aesthetic values before scales turn them into colours/sizes (e.g. a tile's fill).
      mapped = safe({
        raw <- ly$layer_data(p$data)
        lapply(built$plot$layers[[i]]$computed_mapping, function(q) {
          v <- rlang::eval_tidy(q, data = raw)
          if (is.factor(v)) v <- as.character(v)
          if (inherits(v, "Date")) v <- as.numeric(v)
          if (is.atomic(v) && length(v) <= max_rows) v else NULL
        })
      }, list())
    )
  })
  scales <- lapply(built$plot$scales$scales, function(s) list(
    aesthetics = s$aesthetics, class = class(s)[1],
    transform = safe(s$get_transformation()$name, safe(s$trans$name)),
    limits = safe(as.character(s$get_limits())), breaks = safe(as.character(s$get_breaks())),
    levels = safe(if (inherits(s, "ScaleDiscrete")) as.character(s$range$range)),
    name = safe(if (inherits(s$name, "waiver")) NULL else as.character(s$name)),
    guide = safe(if (is.character(s$guide)) s$guide else class(s$guide)[1])
  ))
  # Position scales are trained in the layout (the plot's own scales are untrained templates).
  trained <- function(sc) {
    if (is.null(sc)) return(NULL)
    list(class = class(sc)[1],
         levels = safe(if (inherits(sc, "ScaleDiscrete")) as.character(sc$range$range)),
         range = safe(if (inherits(sc, "ScaleContinuous")) as.numeric(sc$range$range)),
         limits = safe(as.character(sc$get_limits())),
         transform = safe(sc$get_transformation()$name, safe(sc$trans$name)))
  }
  position <- list(x = trained(safe(built$layout$panel_scales_x[[1]])),
                   y = trained(safe(built$layout$panel_scales_y[[1]])))
  facet <- p$facet
  facet_vars <- safe(c(names(facet$params$facets), names(facet$params$rows), names(facet$params$cols)), character())
  panel <- safe(built$layout$layout, NULL)
  list(
    n_layers = length(p$layers), layers = layers, labels = labs, scales = scales,
    position = position,
    facet = class(facet)[1], facet_vars = facet_vars, facet_free = safe(facet$params$free),
    n_panels = if (is.null(panel)) NA_integer_ else nrow(panel),
    coord = class(p$coordinates)[1], coord_limits = safe(lapply(p$coordinates$limits, as.numeric)),
    panel_x_range = safe(as.numeric(built$layout$panel_params[[1]]$x.range)),
    panel_y_range = safe(as.numeric(built$layout$panel_params[[1]]$y.range)),
    legend_position = safe(as.character(p$theme$legend.position))
  )
}

# Convenience: layer `i`'s built data frame from a digest, optionally restricted to a PANEL.
layer_data_of <- function(digest, i = 1L) {
  stopifnot(i <= length(digest$layers))
  digest$layers[[i]]$data
}

# Indices of the digest's layers whose geom class is one of `geoms`.
layers_of <- function(digest, geoms) {
  which(vapply(digest$layers, function(l) l$geom %in% geoms, logical(1)))
}

# Tick order of a discrete position scale (levels of the trained x or y scale), from a digest.
discrete_levels <- function(digest, aesthetic = "x") {
  digest$position[[aesthetic]]$levels
}
