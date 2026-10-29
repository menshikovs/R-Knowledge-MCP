#### control: reference
# Trusted reference: installed.packages(fields = ...) and the documented rules.
package_origin <- function(pkgs) {
  if (!is.character(pkgs) || !length(pkgs) || anyNA(pkgs)) stop("pkgs must be a non-empty character vector without NA")
  ip <- utils::installed.packages(fields = c("Repository", "biocViews"), noCache = TRUE)
  ip <- ip[!duplicated(rownames(ip)), , drop = FALSE]
  one <- function(p) {
    if (!(p %in% rownames(ip))) return(c(p, NA, "not_installed", NA))
    r <- ip[p, ]
    repo <- if (is.na(r[["Repository"]])) NA_character_ else r[["Repository"]]
    origin <- if (identical(unname(r[["Priority"]]), "base")) "base"
      else if (!is.na(repo) && startsWith(repo, "Bioconductor")) "bioconductor"
      else if (is.na(repo) && !is.na(r[["biocViews"]])) "bioconductor"
      else if (!is.na(repo) && repo %in% c("CRAN", "RSPM")) "cran"
      else "unknown"
    rel <- if (origin == "bioconductor" && !is.na(repo) && grepl("^Bioconductor\\s+\\S", repo)) trimws(sub("^Bioconductor\\s+", "", repo)) else NA
    c(p, r[["Version"]], origin, rel)
  }
  m <- t(vapply(pkgs, one, character(4)))
  data.frame(package = unname(m[, 1]), version = unname(m[, 2]), origin = unname(m[, 3]), bioc_release = unname(m[, 4]),
             stringsAsFactors = FALSE)
}

#### control: alternate_packagedescription
# Alternate valid solution: packageDescription() per package.
package_origin <- function(pkgs) {
  stopifnot(is.character(pkgs), length(pkgs) >= 1, !anyNA(pkgs))
  rows <- lapply(pkgs, function(p) {
    if (!nzchar(system.file(package = p))) return(data.frame(package = p, version = NA_character_, origin = "not_installed", bioc_release = NA_character_))
    d <- utils::packageDescription(p)
    repo <- if (is.null(d$Repository)) NA_character_ else d$Repository
    prio <- if (is.null(d$Priority)) "" else d$Priority
    origin <- if (prio == "base") "base" else if (grepl("^Bioconductor", repo %||% "") || (is.na(repo) && !is.null(d$biocViews))) "bioconductor" else if (repo %in% c("CRAN", "RSPM")) "cran" else "unknown"
    rel <- if (origin == "bioconductor" && grepl("^Bioconductor\\s+\\S", repo %||% "")) trimws(sub("^Bioconductor\\s+", "", repo)) else NA_character_
    data.frame(package = p, version = d$Version, origin = origin, bioc_release = rel)
  })
  do.call(rbind, rows)
}
`%||%` <- function(a, b) if (is.null(a) || (length(a) == 1L && is.na(a))) b else a

#### control: wrong_repository_field_used_as_origin
# Plausible wrong strategy: the Repository field is the origin (RSPM and NA leak through).
package_origin <- function(pkgs) {
  stopifnot(is.character(pkgs), length(pkgs) >= 1, !anyNA(pkgs))
  ip <- utils::installed.packages(fields = "Repository", noCache = TRUE)
  idx <- match(pkgs, rownames(ip))
  data.frame(package = pkgs, version = unname(ip[idx, "Version"]),
             origin = ifelse(is.na(idx), "not_installed", ifelse(is.na(ip[idx, "Repository"]), "base", sub("\\s.*$", "", ip[idx, "Repository"]))),
             bioc_release = NA_character_, stringsAsFactors = FALSE)
}

#### control: wrong_recommended_treated_as_base
# Plausible wrong strategy: packages with any Priority are called base.
package_origin <- function(pkgs) {
  stopifnot(is.character(pkgs), length(pkgs) >= 1, !anyNA(pkgs))
  ip <- utils::installed.packages(fields = "Repository", noCache = TRUE)
  idx <- match(pkgs, rownames(ip))
  repo <- ip[idx, "Repository"]
  origin <- ifelse(is.na(idx), "not_installed", ifelse(!is.na(ip[idx, "Priority"]), "base",
            ifelse(grepl("^Bioconductor", repo), "bioconductor", ifelse(repo %in% c("CRAN", "RSPM"), "cran", "unknown"))))
  data.frame(package = pkgs, version = unname(ip[idx, "Version"]), origin = unname(origin),
             bioc_release = ifelse(origin == "bioconductor", trimws(sub("^Bioconductor", "", repo)), NA), stringsAsFactors = FALSE)
}

#### control: wrong_rspm_not_cran
# Plausible wrong strategy: only the literal value CRAN counts as CRAN.
package_origin <- function(pkgs) {
  stopifnot(is.character(pkgs), length(pkgs) >= 1, !anyNA(pkgs))
  ip <- utils::installed.packages(fields = "Repository", noCache = TRUE)
  idx <- match(pkgs, rownames(ip))
  repo <- ip[idx, "Repository"]
  origin <- ifelse(is.na(idx), "not_installed", ifelse(ip[idx, "Priority"] %in% "base", "base",
            ifelse(grepl("^Bioconductor", repo), "bioconductor", ifelse(repo %in% "CRAN", "cran", "unknown"))))
  data.frame(package = pkgs, version = unname(ip[idx, "Version"]), origin = unname(origin),
             bioc_release = ifelse(origin == "bioconductor", trimws(sub("^Bioconductor", "", repo)), NA), stringsAsFactors = FALSE)
}

#### control: wrong_unique_rows_and_sorted
# Plausible wrong strategy: the input is de-duplicated and sorted.
package_origin <- function(pkgs) {
  stopifnot(is.character(pkgs), length(pkgs) >= 1, !anyNA(pkgs))
  pkgs <- sort(unique(pkgs))
  ip <- utils::installed.packages(fields = "Repository", noCache = TRUE)
  idx <- match(pkgs, rownames(ip))
  repo <- ip[idx, "Repository"]
  origin <- ifelse(is.na(idx), "not_installed", ifelse(ip[idx, "Priority"] %in% "base", "base",
            ifelse(grepl("^Bioconductor", repo), "bioconductor", ifelse(repo %in% c("CRAN", "RSPM"), "cran", "unknown"))))
  data.frame(package = pkgs, version = unname(ip[idx, "Version"]), origin = unname(origin),
             bioc_release = ifelse(origin == "bioconductor", trimws(sub("^Bioconductor", "", repo)), NA), stringsAsFactors = FALSE)
}

#### control: wrong_missing_release_text
# Plausible wrong strategy: the release is never extracted.
package_origin <- function(pkgs) {
  stopifnot(is.character(pkgs), length(pkgs) >= 1, !anyNA(pkgs))
  ip <- utils::installed.packages(fields = "Repository", noCache = TRUE)
  idx <- match(pkgs, rownames(ip))
  repo <- ip[idx, "Repository"]
  origin <- ifelse(is.na(idx), "not_installed", ifelse(ip[idx, "Priority"] %in% "base", "base",
            ifelse(grepl("^Bioconductor", repo), "bioconductor", ifelse(repo %in% c("CRAN", "RSPM"), "cran", "unknown"))))
  data.frame(package = pkgs, version = unname(ip[idx, "Version"]), origin = unname(origin),
             bioc_release = NA_character_, stringsAsFactors = FALSE)
}

#### control: edge_no_argument_validation
# Boundary case: right on valid input but an empty vector or NA is accepted (expected: not fully correct).
# expect: fail
package_origin <- function(pkgs) {
  ip <- utils::installed.packages(fields = "Repository", noCache = TRUE)
  idx <- match(pkgs, rownames(ip))
  repo <- ip[idx, "Repository"]
  origin <- ifelse(is.na(idx), "not_installed", ifelse(ip[idx, "Priority"] %in% "base", "base",
            ifelse(grepl("^Bioconductor", repo), "bioconductor", ifelse(repo %in% c("CRAN", "RSPM"), "cran", "unknown"))))
  rel <- ifelse(origin == "bioconductor", trimws(sub("^Bioconductor", "", repo)), NA_character_)
  data.frame(package = pkgs, version = unname(ip[idx, "Version"]), origin = unname(origin), bioc_release = unname(rel),
             stringsAsFactors = FALSE)
}

#### control: malformed_returns_named_vector
# Malformed submission: a named character vector.
# expect: fail
package_origin <- function(pkgs) {
  ip <- utils::installed.packages(fields = "Repository")
  stats::setNames(ip[match(pkgs, rownames(ip)), "Repository"], pkgs)
}

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
package_origin <- function(pkgs) stop("todo")
