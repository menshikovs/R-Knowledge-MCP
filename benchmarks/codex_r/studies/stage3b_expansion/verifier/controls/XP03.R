#### control: reference
# Trusted reference: closure through packageDescription(), numeric_version comparison.
minimum_r_version <- function(pkg) {
  if (!is.character(pkg) || length(pkg) != 1L || is.na(pkg) || !nzchar(system.file(package = pkg))) stop("pkg must name an installed package")
  fields <- function(p, f) {
    x <- utils::packageDescription(p)[[f]]
    if (is.null(x) || is.na(x)) return(character())
    x <- trimws(strsplit(gsub("\\s+", " ", x), ",")[[1]])
    x[nzchar(x)]
  }
  names_of <- function(p) {
    x <- unlist(lapply(c("Depends", "Imports", "LinkingTo"), function(f) fields(p, f)))
    setdiff(trimws(sub("\\(.*$", "", x)), "R")
  }
  is_base <- function(p) nzchar(system.file(package = p)) && identical(utils::packageDescription(p)$Priority, "base")
  seen <- pkg
  queue <- names_of(pkg)
  while (length(queue)) {
    p <- queue[1]
    queue <- queue[-1]
    if (p %in% seen || !nzchar(system.file(package = p)) || is_base(p)) next
    seen <- c(seen, p)
    queue <- c(queue, names_of(p))
  }
  vers <- character()
  for (p in seen) {
    for (d in fields(p, "Depends")) {
      m <- regmatches(d, regexec("^R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)$", d))[[1]]
      if (length(m)) vers <- c(vers, m[[2]])
    }
  }
  if (!length(vers)) return(NA_character_)
  best <- max(numeric_version(gsub("-", ".", vers)))
  parts <- unlist(best)
  while (length(parts) < 3L) parts <- c(parts, 0L)
  paste(parts, collapse = ".")
}

#### control: alternate_tools_package_dependencies
# Alternate valid solution: closure from tools::package_dependencies(), requirements from installed.packages().
minimum_r_version <- function(pkg) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, !is.na(pkg), pkg %in% rownames(ip))
  deps <- tools::package_dependencies(pkg, db = ip, which = c("Depends", "Imports", "LinkingTo"), recursive = TRUE)[[1]]
  deps <- deps[deps %in% rownames(ip) & !(ip[match(deps, rownames(ip)), "Priority"] %in% "base")]
  dep_field <- ip[unique(c(pkg, deps)), "Depends"]
  vers <- unlist(lapply(dep_field, function(x) {
    if (is.na(x)) return(character())
    m <- regmatches(x, gregexpr("R\\s*\\(>=\\s*[0-9][0-9.-]*\\s*\\)", x))[[1]]
    sub("^R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)$", "\\1", m)
  }))
  if (!length(vers)) return(NA_character_)
  p <- unlist(max(numeric_version(gsub("-", ".", vers))))
  p <- c(p, rep(0L, max(0L, 3L - length(p))))
  paste(p, collapse = ".")
}

#### control: wrong_own_requirement_only
# Plausible wrong strategy: only the package's own Depends: R (>= x) line is read.
minimum_r_version <- function(pkg) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, !is.na(pkg), pkg %in% rownames(ip))
  x <- ip[pkg, "Depends"]
  if (is.na(x)) return(NA_character_)
  m <- regmatches(x, regexec("R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)", x))[[1]]
  if (!length(m)) return(NA_character_)
  p <- unlist(numeric_version(gsub("-", ".", m[[2]])))
  p <- c(p, rep(0L, max(0L, 3L - length(p))))
  paste(p, collapse = ".")
}

#### control: wrong_lexical_comparison
# Plausible wrong strategy: versions compared as text, so "4.9" beats "4.10".
minimum_r_version <- function(pkg) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, !is.na(pkg), pkg %in% rownames(ip))
  deps <- tools::package_dependencies(pkg, db = ip, which = c("Depends", "Imports", "LinkingTo"), recursive = TRUE)[[1]]
  deps <- deps[deps %in% rownames(ip) & !(ip[match(deps, rownames(ip)), "Priority"] %in% "base")]
  x <- ip[unique(c(pkg, deps)), "Depends"]
  vers <- unlist(lapply(x, function(s) {
    if (is.na(s)) return(character())
    regmatches(s, regexec("R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)", s))[[1]][-1]
  }))
  if (!length(vers)) return(NA_character_)
  max(vers)
}

#### control: wrong_base_packages_followed
# Plausible wrong strategy: base packages are followed too, so their R requirement counts.
minimum_r_version <- function(pkg) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, !is.na(pkg), pkg %in% rownames(ip))
  deps <- tools::package_dependencies(pkg, db = ip, which = c("Depends", "Imports", "LinkingTo"), recursive = TRUE)[[1]]
  deps <- deps[deps %in% rownames(ip)]
  x <- ip[unique(c(pkg, deps)), "Depends"]
  vers <- unlist(lapply(x, function(s) {
    if (is.na(s)) return(character())
    regmatches(s, regexec("R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)", s))[[1]][-1]
  }))
  v <- c(vers, "4.5.2")
  p <- unlist(max(numeric_version(gsub("-", ".", v))))
  p <- c(p, rep(0L, max(0L, 3L - length(p))))
  paste(p, collapse = ".")
}

#### control: wrong_no_normalisation
# Plausible wrong strategy: the stated version is returned as written (two components stay two).
minimum_r_version <- function(pkg) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, !is.na(pkg), pkg %in% rownames(ip))
  deps <- tools::package_dependencies(pkg, db = ip, which = c("Depends", "Imports", "LinkingTo"), recursive = TRUE)[[1]]
  deps <- deps[deps %in% rownames(ip) & !(ip[match(deps, rownames(ip)), "Priority"] %in% "base")]
  x <- ip[unique(c(pkg, deps)), "Depends"]
  vers <- unlist(lapply(x, function(s) {
    if (is.na(s)) return(character())
    regmatches(s, regexec("R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)", s))[[1]][-1]
  }))
  if (!length(vers)) return(NA_character_)
  vers[which.max(as.numeric(sapply(strsplit(vers, "[.-]"), function(z) sum(as.numeric(z) / 1000^(seq_along(z) - 1)))))]
}

#### control: edge_no_argument_validation
# Boundary case: right for valid input; unknown packages are not rejected (expected: not fully correct).
# expect: fail
minimum_r_version <- function(pkg) {
  ip <- utils::installed.packages(noCache = TRUE)
  deps <- tools::package_dependencies(pkg, db = ip, which = c("Depends", "Imports", "LinkingTo"), recursive = TRUE)[[1]]
  deps <- deps[deps %in% rownames(ip) & !(ip[match(deps, rownames(ip)), "Priority"] %in% "base")]
  x <- ip[intersect(unique(c(pkg, deps)), rownames(ip)), "Depends"]
  vers <- unlist(lapply(x, function(s) {
    if (is.na(s)) return(character())
    regmatches(s, regexec("R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)", s))[[1]][-1]
  }))
  if (!length(vers)) return(NA_character_)
  p <- unlist(max(numeric_version(gsub("-", ".", vers))))
  p <- c(p, rep(0L, max(0L, 3L - length(p))))
  paste(p, collapse = ".")
}

#### control: malformed_returns_numeric_version
# Malformed submission: a numeric_version object instead of a string.
# expect: fail
minimum_r_version <- function(pkg) numeric_version("4.1.0")

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
minimum_r_version <- function(pkg) stop("todo")
