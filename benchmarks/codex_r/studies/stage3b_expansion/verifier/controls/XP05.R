#### control: reference
# Trusted reference: numeric_version() comparison (with the hyphen-as-dot rule applied explicitly).
check_requirements <- function(req) {
  if (!is.data.frame(req) || !all(c("package", "op", "version") %in% names(req))) stop("req needs package, op and version")
  ops <- c(">=", ">", "<=", "<", "==", "!=")
  p <- as.character(req$package)
  o <- as.character(req$op)
  v <- as.character(req$version)
  if (anyNA(p) || anyNA(o) || anyNA(v)) stop("missing values")
  if (!all(o %in% ops)) stop("bad operator")
  if (!all(grepl("^[0-9]+([.-][0-9]+)*$", v))) stop("bad version")
  ip <- utils::installed.packages(noCache = TRUE)
  inst <- unname(ifelse(p %in% rownames(ip), ip[match(p, rownames(ip)), "Version"], NA_character_))
  status <- vapply(seq_along(p), function(i) {
    if (is.na(inst[i])) return("not_installed")
    a <- numeric_version(gsub("-", ".", inst[i]))
    b <- numeric_version(gsub("-", ".", v[i]))
    ok <- switch(o[i], ">=" = a >= b, ">" = a > b, "<=" = a <= b, "<" = a < b, "==" = a == b, "!=" = a != b)
    if (ok) "satisfied" else "unsatisfied"
  }, character(1))
  data.frame(package = p, op = o, required = v, installed = inst, status = status, stringsAsFactors = FALSE)
}

#### control: alternate_compareversion
# Alternate valid solution: utils::compareVersion().
check_requirements <- function(req) {
  stopifnot(is.data.frame(req), all(c("package", "op", "version") %in% names(req)))
  p <- as.character(req$package); o <- as.character(req$op); v <- as.character(req$version)
  stopifnot(!anyNA(p), !anyNA(o), !anyNA(v), all(o %in% c(">=", ">", "<=", "<", "==", "!=")),
            all(grepl("^[0-9]+([.-][0-9]+)*$", v)))
  inst <- vapply(p, function(x) if (nzchar(system.file(package = x))) as.character(utils::packageVersion(x)) else NA_character_, "")
  # packageVersion() prints 7.3-65 as 7.3.65; the DESCRIPTION text is what must be reported.
  txt <- vapply(p, function(x) if (nzchar(system.file(package = x))) utils::packageDescription(x)$Version else NA_character_, "")
  status <- vapply(seq_along(p), function(i) {
    if (is.na(txt[i])) return("not_installed")
    c <- utils::compareVersion(txt[i], v[i])
    r <- switch(o[i], ">=" = c >= 0, ">" = c > 0, "<=" = c <= 0, "<" = c < 0, "==" = c == 0, "!=" = c != 0)
    if (r) "satisfied" else "unsatisfied"
  }, "")
  data.frame(package = p, op = o, required = v, installed = unname(txt), status = unname(status), stringsAsFactors = FALSE)
}

#### control: wrong_textual_comparison
# Plausible wrong strategy: versions compared as strings.
check_requirements <- function(req) {
  stopifnot(is.data.frame(req), all(c("package", "op", "version") %in% names(req)))
  p <- as.character(req$package); o <- as.character(req$op); v <- as.character(req$version)
  stopifnot(!anyNA(p), !anyNA(o), !anyNA(v), all(o %in% c(">=", ">", "<=", "<", "==", "!=")), all(grepl("^[0-9]+([.-][0-9]+)*$", v)))
  ip <- utils::installed.packages(noCache = TRUE)
  inst <- unname(ifelse(p %in% rownames(ip), ip[match(p, rownames(ip)), "Version"], NA_character_))
  status <- vapply(seq_along(p), function(i) {
    if (is.na(inst[i])) return("not_installed")
    r <- do.call(o[i], list(inst[i], v[i]))
    if (r) "satisfied" else "unsatisfied"
  }, "")
  data.frame(package = p, op = o, required = v, installed = inst, status = status, stringsAsFactors = FALSE)
}

#### control: wrong_hyphen_not_a_separator
# Plausible wrong strategy: 7.3-65 is parsed as 7.3 (the hyphenated tail is dropped).
check_requirements <- function(req) {
  stopifnot(is.data.frame(req), all(c("package", "op", "version") %in% names(req)))
  p <- as.character(req$package); o <- as.character(req$op); v <- as.character(req$version)
  stopifnot(!anyNA(p), !anyNA(o), !anyNA(v), all(o %in% c(">=", ">", "<=", "<", "==", "!=")), all(grepl("^[0-9]+([.-][0-9]+)*$", v)))
  ip <- utils::installed.packages(noCache = TRUE)
  inst <- unname(ifelse(p %in% rownames(ip), ip[match(p, rownames(ip)), "Version"], NA_character_))
  status <- vapply(seq_along(p), function(i) {
    if (is.na(inst[i])) return("not_installed")
    a <- numeric_version(sub("-.*$", "", inst[i]))
    b <- numeric_version(sub("-.*$", "", v[i]))
    r <- switch(o[i], ">=" = a >= b, ">" = a > b, "<=" = a <= b, "<" = a < b, "==" = a == b, "!=" = a != b)
    if (r) "satisfied" else "unsatisfied"
  }, "")
  data.frame(package = p, op = o, required = v, installed = inst, status = status, stringsAsFactors = FALSE)
}

#### control: wrong_not_installed_is_an_error
# Plausible wrong strategy: a package that is not installed aborts the whole check.
check_requirements <- function(req) {
  stopifnot(is.data.frame(req), all(c("package", "op", "version") %in% names(req)))
  p <- as.character(req$package); o <- as.character(req$op); v <- as.character(req$version)
  stopifnot(!anyNA(p), !anyNA(o), !anyNA(v), all(o %in% c(">=", ">", "<=", "<", "==", "!=")), all(grepl("^[0-9]+([.-][0-9]+)*$", v)))
  inst <- vapply(p, function(x) utils::packageDescription(x, fields = "Version")$Version, "")
  status <- vapply(seq_along(p), function(i) {
    a <- numeric_version(gsub("-", ".", inst[i])); b <- numeric_version(gsub("-", ".", v[i]))
    r <- switch(o[i], ">=" = a >= b, ">" = a > b, "<=" = a <= b, "<" = a < b, "==" = a == b, "!=" = a != b)
    if (r) "satisfied" else "unsatisfied"
  }, "")
  data.frame(package = p, op = o, required = v, installed = unname(inst), status = unname(status), stringsAsFactors = FALSE)
}

#### control: edge_no_input_validation
# Boundary case: right for valid tables; bad operators and versions are not rejected (expected: not fully correct).
# expect: fail
check_requirements <- function(req) {
  p <- as.character(req$package); o <- as.character(req$op); v <- as.character(req$version)
  ip <- utils::installed.packages(noCache = TRUE)
  inst <- unname(ifelse(p %in% rownames(ip), ip[match(p, rownames(ip)), "Version"], NA_character_))
  status <- vapply(seq_along(p), function(i) {
    if (is.na(inst[i])) return("not_installed")
    a <- numeric_version(gsub("-", ".", inst[i])); b <- suppressWarnings(numeric_version(gsub("-", ".", v[i]), strict = FALSE))
    r <- tryCatch(switch(o[i], ">=" = a >= b, ">" = a > b, "<=" = a <= b, "<" = a < b, "==" = a == b, "!=" = a != b), error = function(e) FALSE)
    if (isTRUE(r)) "satisfied" else "unsatisfied"
  }, character(1))
  data.frame(package = p, op = o, required = v, installed = inst, status = status, stringsAsFactors = FALSE)
}

#### control: malformed_returns_logical
# Malformed submission: only a logical vector.
# expect: fail
check_requirements <- function(req) rep(TRUE, nrow(req))

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
check_requirements <- function(req) NULL
