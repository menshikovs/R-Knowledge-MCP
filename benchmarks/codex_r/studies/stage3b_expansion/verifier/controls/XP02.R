#### control: reference
# Trusted reference: tools::package_dependencies(reverse = TRUE, recursive = FALSE).
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ok_types <- c("Depends", "Imports", "LinkingTo", "Suggests", "Enhances")
  ip <- utils::installed.packages(noCache = TRUE)
  if (!is.character(pkg) || length(pkg) != 1L || is.na(pkg) || !(pkg %in% rownames(ip))) stop("pkg must name an installed package")
  if (!is.character(types) || !length(types) || !all(types %in% ok_types)) stop("bad types")
  r <- tools::package_dependencies(pkg, db = ip, which = types, reverse = TRUE, recursive = FALSE)[[1]]
  sort(unique(setdiff(r, pkg)), method = "radix")
}

#### control: alternate_manual_scan
# Alternate valid solution: manual scan of packageDescription() fields.
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ok_types <- c("Depends", "Imports", "LinkingTo", "Suggests", "Enhances")
  stopifnot(is.character(pkg), length(pkg) == 1, !is.na(pkg), nzchar(system.file(package = pkg)))
  stopifnot(is.character(types), length(types) >= 1, all(types %in% ok_types))
  all <- rownames(utils::installed.packages(noCache = TRUE))
  hit <- vapply(setdiff(unique(all), pkg), function(p) {
    d <- utils::packageDescription(p, fields = types)
    f <- unlist(lapply(d, function(z) if (is.na(z)) character() else strsplit(gsub("\\s+", " ", z), ",")[[1]]))
    pkg %in% trimws(sub("\\(.*$", "", trimws(f)))
  }, logical(1))
  sort(names(hit)[hit], method = "radix")
}

#### control: wrong_substring_matching
# Plausible wrong strategy: grepl() on the raw field, so cli matches clipr.
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE, fields = "LinkingTo")
  stopifnot(is.character(pkg), length(pkg) == 1, pkg %in% rownames(ip))
  cols <- intersect(types, colnames(ip))
  hit <- apply(ip[, cols, drop = FALSE], 1, function(r) any(grepl(pkg, r[!is.na(r)], fixed = TRUE)))
  sort(setdiff(rownames(ip)[hit], pkg), method = "radix")
}

#### control: wrong_recursive_dependencies
# Plausible wrong strategy: reverse dependencies are computed recursively.
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, pkg %in% rownames(ip), all(types %in% c("Depends", "Imports", "LinkingTo", "Suggests", "Enhances")))
  r <- tools::package_dependencies(pkg, db = ip, which = types, reverse = TRUE, recursive = TRUE)[[1]]
  sort(unique(setdiff(r, pkg)), method = "radix")
}

#### control: wrong_ignores_linkingto_and_types
# Plausible wrong strategy: only Imports is searched whatever `types` says.
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, pkg %in% rownames(ip))
  r <- tools::package_dependencies(pkg, db = ip, which = "Imports", reverse = TRUE)[[1]]
  sort(unique(setdiff(r, pkg)), method = "radix")
}

#### control: wrong_only_user_library_searched
# Plausible wrong strategy: only the first library path is searched.
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(lib.loc = .libPaths()[1], noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, nzchar(system.file(package = pkg)))
  r <- tools::package_dependencies(pkg, db = ip, which = types, reverse = TRUE)[[1]]
  sort(unique(setdiff(r, pkg)), method = "radix")
}

#### control: edge_no_argument_validation
# Boundary case: right for valid input but nothing is validated (expected: not fully correct).
# expect: fail
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE)
  r <- tools::package_dependencies(pkg, db = ip, which = types, reverse = TRUE)[[1]]
  if (is.null(r)) r <- character()
  sort(unique(setdiff(r, pkg)), method = "radix")
}

#### control: malformed_returns_list
# Malformed submission: a list as returned by package_dependencies().
# expect: fail
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  tools::package_dependencies(pkg, db = utils::installed.packages(), reverse = TRUE)
}

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
reverse_dependencies <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) stop("todo")
