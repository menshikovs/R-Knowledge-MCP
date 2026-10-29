#### control: reference
# Trusted reference: breadth-first search over packageDescription() of installed packages.
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ok_types <- c("Depends", "Imports", "LinkingTo")
  if (!is.character(pkg) || length(pkg) != 1L || is.na(pkg) || !nzchar(system.file(package = pkg))) {
    stop("pkg must name an installed package")
  }
  if (!is.character(types) || !length(types) || !all(types %in% ok_types)) stop("bad types")
  fields <- function(p) {
    d <- utils::packageDescription(p)
    x <- unlist(lapply(types, function(f) if (is.null(d[[f]]) || is.na(d[[f]])) character() else strsplit(gsub("\\s+", " ", d[[f]]), ",")[[1]]))
    x <- trimws(sub("\\(.*$", "", trimws(x)))
    setdiff(x[nzchar(x)], "R")
  }
  base_pkg <- function(p) identical(utils::packageDescription(p)$Priority, "base")
  seen <- character()
  queue <- fields(pkg)
  while (length(queue)) {
    p <- queue[1]
    queue <- queue[-1]
    if (p %in% seen || p == pkg || base_pkg(p)) next
    seen <- c(seen, p)
    queue <- c(queue, fields(p))
  }
  sort(seen, method = "radix")
}

#### control: alternate_tools_package_dependencies
# Alternate valid solution: tools::package_dependencies(recursive = TRUE) on the installed-package database.
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ok_types <- c("Depends", "Imports", "LinkingTo")
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, !is.na(pkg), pkg %in% rownames(ip))
  stopifnot(is.character(types), length(types) >= 1, all(types %in% ok_types))
  deps <- tools::package_dependencies(pkg, db = ip, which = types, recursive = TRUE)[[1]]
  deps <- setdiff(deps, c("R", pkg))
  is_base <- deps %in% rownames(ip) & ip[match(deps, rownames(ip)), "Priority"] %in% "base"
  sort(unique(deps[!is_base]), method = "radix")
}

#### control: wrong_direct_dependencies_only
# Plausible wrong strategy: only the direct dependencies are listed.
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  stopifnot(is.character(pkg), length(pkg) == 1, nzchar(system.file(package = pkg)))
  ip <- utils::installed.packages(noCache = TRUE)
  x <- unlist(strsplit(gsub("\\s+", " ", paste(ip[pkg, intersect(types, colnames(ip))], collapse = ",")), ","))
  x <- trimws(sub("\\(.*$", "", trimws(x)))
  x <- setdiff(x[nzchar(x) & x != "NA"], "R")
  sort(x, method = "radix")
}

#### control: wrong_base_packages_included
# Plausible wrong strategy: packages that ship with R are not removed.
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, pkg %in% rownames(ip))
  sort(setdiff(tools::package_dependencies(pkg, db = ip, which = types, recursive = TRUE)[[1]], c("R", pkg)), method = "radix")
}

#### control: wrong_suggests_always_included
# Plausible wrong strategy: Suggests is added to every closure.
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, pkg %in% rownames(ip))
  deps <- tools::package_dependencies(pkg, db = ip, which = c(types, "Suggests"), recursive = TRUE)[[1]]
  deps <- setdiff(deps, c("R", pkg))
  deps <- deps[!(deps %in% rownames(ip) & ip[match(deps, rownames(ip)), "Priority"] %in% "base")]
  sort(unique(deps), method = "radix")
}

#### control: wrong_locale_sort_and_default_types_ignored
# Plausible wrong strategy: always uses Imports only and sorts in the session locale.
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE)
  stopifnot(is.character(pkg), length(pkg) == 1, pkg %in% rownames(ip))
  deps <- tools::package_dependencies(pkg, db = ip, which = "Imports", recursive = TRUE)[[1]]
  deps <- setdiff(deps, c("R", pkg))
  sort(deps[!(deps %in% rownames(ip) & ip[match(deps, rownames(ip)), "Priority"] %in% "base")])
}

#### control: edge_no_argument_validation
# Boundary case: right for valid input but unknown packages and bad types are not rejected (expected: fail).
# expect: fail
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  ip <- utils::installed.packages(noCache = TRUE)
  deps <- tools::package_dependencies(pkg, db = ip, which = types, recursive = TRUE)[[1]]
  deps <- setdiff(deps, c("R", pkg))
  if (is.null(deps)) deps <- character()
  deps <- deps[!(deps %in% rownames(ip) & ip[match(deps, rownames(ip)), "Priority"] %in% "base")]
  sort(unique(deps), method = "radix")
}

#### control: malformed_returns_data_frame
# Malformed submission: the installed-package matrix row.
# expect: fail
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) {
  as.data.frame(utils::installed.packages()[pkg, , drop = FALSE])
}

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
dependency_closure <- function(pkg, types = c("Depends", "Imports", "LinkingTo")) stop("todo")
