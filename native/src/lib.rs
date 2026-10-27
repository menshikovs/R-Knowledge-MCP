//! Optional accelerators for `cran_knowledge_mcp`.
//!
//! Every function mirrors a pure-Python reference implementation exactly and is
//! checked against it by parity tests. When an input needs Unicode character
//! classes whose Python and Rust definitions differ, the function returns `None`
//! and the caller runs the Python implementation instead of guessing.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyTuple};

/// Bumped whenever a signature or result shape changes; Python checks it on import.
const ABI_VERSION: u32 = 3;
const MAX_ARGUMENT_CHARS: usize = 2000;
/// Nested arguments repeat their parent text; cap the total copied per scan.
const MAX_TOTAL_ARGUMENT_CHARS: usize = 1_000_000;
const TRUNCATED_SUFFIX: &str = " …[truncated]";

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Identifier,
    Str,
    Number,
    Operator,
    Punctuation,
}

struct Token {
    kind: Kind,
    value: String,
    start: usize,
    end: usize,
    line: usize,
}

#[derive(Debug)]
enum ScanError {
    /// Python's `KnowledgeError("invalid_r_syntax", message)`.
    Syntax(String),
    /// Non-ASCII outside strings/comments: defer to the Python implementation.
    NeedsPython,
}

/// Python's `str.isspace()` set (`_PyUnicode_IsWhitespace`), used by `str.strip()`.
fn py_is_space(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n'
            | '\u{0b}'
            | '\u{0c}'
            | '\r'
            | '\u{1c}'..='\u{1f}'
            | ' '
            | '\u{85}'
            | '\u{a0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200a}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202f}'
            | '\u{205f}'
            | '\u{3000}'
    )
}

fn ascii_only(c: char) -> Result<char, ScanError> {
    if c.is_ascii() {
        Ok(c)
    } else {
        Err(ScanError::NeedsPython)
    }
}

fn is_alpha(c: char) -> Result<bool, ScanError> {
    Ok(ascii_only(c)?.is_ascii_alphabetic())
}

fn is_digit(c: char) -> Result<bool, ScanError> {
    Ok(ascii_only(c)?.is_ascii_digit())
}

fn is_alnum(c: char) -> Result<bool, ScanError> {
    Ok(ascii_only(c)?.is_ascii_alphanumeric())
}

fn find(chars: &[char], needle: &[char], from: usize) -> Option<usize> {
    if needle.is_empty() || from > chars.len() {
        return None;
    }
    chars[from..]
        .windows(needle.len())
        .position(|window| window == needle)
        .map(|offset| from + offset)
}

fn starts_with(chars: &[char], at: usize, pattern: &str) -> bool {
    let rest = chars.get(at..).unwrap_or(&[]);
    let mut expected = pattern.chars();
    rest.iter()
        .zip(expected.by_ref())
        .all(|(actual, wanted)| actual == &wanted)
        && expected.next().is_none()
}

const OPERATORS: [&str; 18] = [
    ":::", "<<-", "->>", "::", "<-", "->", "==", "!=", "<=", ">=", "&&", "||", "|>", ":=", "%%",
    "%/%", "&", "&&",
];

fn closing_for(bracket: char) -> char {
    match bracket {
        '(' => ')',
        '[' => ']',
        _ => '}',
    }
}

fn tokenize(chars: &[char]) -> Result<Vec<Token>, ScanError> {
    let n = chars.len();
    let mut tokens = Vec::new();
    let (mut i, mut line) = (0usize, 1usize);
    while i < n {
        let c = chars[i];
        if matches!(c, ' ' | '\t' | '\r' | '\u{0c}') {
            i += 1;
            continue;
        }
        if c == '\n' {
            line += 1;
            i += 1;
            continue;
        }
        if c == '#' {
            i = find(chars, &['\n'], i).unwrap_or(n);
            continue;
        }
        let (start, start_line) = (i, line);
        if (c == 'r' || c == 'R') && i + 1 < n && (chars[i + 1] == '\'' || chars[i + 1] == '"') {
            let quote = chars[i + 1];
            let mut cursor = i + 2;
            while cursor < n && chars[cursor] == '-' {
                cursor += 1;
            }
            if cursor >= n || !matches!(chars[cursor], '(' | '[' | '{') {
                return Err(ScanError::Syntax(format!(
                    "Malformed raw string at line {start_line}"
                )));
            }
            let dashes = cursor - (i + 2);
            let mut terminator = vec![closing_for(chars[cursor])];
            terminator.extend(std::iter::repeat_n('-', dashes));
            terminator.push(quote);
            let body_start = cursor + 1;
            let stop = find(chars, &terminator, body_start).ok_or_else(|| {
                ScanError::Syntax(format!("Unterminated raw string at line {start_line}"))
            })?;
            i = stop + terminator.len();
            line += chars[start..i].iter().filter(|&&ch| ch == '\n').count();
            tokens.push(Token {
                kind: Kind::Str,
                value: chars[body_start..stop].iter().collect(),
                start,
                end: i,
                line: start_line,
            });
            continue;
        }
        if c == '\'' || c == '"' || c == '`' {
            let quote = c;
            i += 1;
            let mut value = String::new();
            let mut closed = false;
            while i < n {
                let current = chars[i];
                if current == '\\' && i + 1 < n {
                    value.push(current);
                    value.push(chars[i + 1]);
                    if chars[i + 1] == '\n' {
                        line += 1;
                    }
                    i += 2;
                    continue;
                }
                if current == quote {
                    i += 1;
                    closed = true;
                    break;
                }
                if current == '\n' {
                    line += 1;
                }
                value.push(current);
                i += 1;
            }
            tokens.push(Token {
                kind: if quote == '`' {
                    Kind::Identifier
                } else {
                    Kind::Str
                },
                value,
                start,
                end: i,
                line: start_line,
            });
            if !closed {
                return Err(ScanError::Syntax(format!(
                    "Unterminated {quote} at line {start_line}"
                )));
            }
            continue;
        }
        // Like Python, only a leading '.' needs its following character classified.
        let dot_then_digit = c == '.' && i + 1 < n && is_digit(chars[i + 1])?;
        if is_alpha(c)? || c == '_' || (c == '.' && i + 1 < n && !dot_then_digit) {
            i += 1;
            while i < n && (is_alnum(chars[i])? || chars[i] == '.' || chars[i] == '_') {
                i += 1;
            }
            tokens.push(Token {
                kind: Kind::Identifier,
                value: chars[start..i].iter().collect(),
                start,
                end: i,
                line: start_line,
            });
            continue;
        }
        if is_digit(c)? || dot_then_digit {
            i += 1;
            while i < n && (is_alnum(chars[i])? || chars[i] == '.') {
                i += 1;
            }
            if i < n && (chars[i] == '+' || chars[i] == '-') && matches!(chars[i - 1], 'e' | 'E') {
                i += 1;
                while i < n && is_digit(chars[i])? {
                    i += 1;
                }
            }
            tokens.push(Token {
                kind: Kind::Number,
                value: chars[start..i].iter().collect(),
                start,
                end: i,
                line: start_line,
            });
            continue;
        }
        if c == '%' {
            if let Some(stop) = find(chars, &['%'], i + 1) {
                i = stop + 1;
                tokens.push(Token {
                    kind: Kind::Operator,
                    value: chars[start..i].iter().collect(),
                    start,
                    end: i,
                    line: start_line,
                });
                continue;
            }
        }
        if let Some(operator) = OPERATORS.iter().find(|op| starts_with(chars, i, op)) {
            i += operator.chars().count();
            tokens.push(Token {
                kind: Kind::Operator,
                value: (*operator).to_string(),
                start,
                end: i,
                line: start_line,
            });
        } else {
            // Non-ASCII characters were already deferred by the class checks above.
            i += 1;
            tokens.push(Token {
                kind: Kind::Punctuation,
                value: c.to_string(),
                start,
                end: i,
                line: start_line,
            });
        }
    }
    Ok(tokens)
}

fn bracket_matches(tokens: &[Token]) -> Result<Vec<Option<usize>>, ScanError> {
    let mut matches = vec![None; tokens.len()];
    let mut stack: Vec<usize> = Vec::new();
    for (index, token) in tokens.iter().enumerate() {
        if token.kind != Kind::Punctuation {
            continue;
        }
        match token.value.as_str() {
            "(" | "[" | "{" => stack.push(index),
            ")" | "]" | "}" => {
                let expected = stack
                    .last()
                    .map(|&open| closing_for(tokens[open].value.chars().next().unwrap()));
                if expected.map(String::from) != Some(token.value.clone()) {
                    return Err(ScanError::Syntax(format!(
                        "Unmatched {} at line {}",
                        token.value, token.line
                    )));
                }
                matches[stack.pop().unwrap()] = Some(index);
            }
            _ => {}
        }
    }
    if let Some(&open) = stack.last() {
        return Err(ScanError::Syntax(format!(
            "Unclosed {} at line {}",
            tokens[open].value, tokens[open].line
        )));
    }
    Ok(matches)
}

fn py_strip(chars: &[char]) -> String {
    let mut first = 0;
    let mut last = chars.len();
    while first < last && py_is_space(chars[first]) {
        first += 1;
    }
    while last > first && py_is_space(chars[last - 1]) {
        last -= 1;
    }
    chars[first..last].iter().collect()
}

fn argument_text(chars: &[char], start: usize, end: usize, budget: &mut usize) -> String {
    let limit = MAX_ARGUMENT_CHARS.min(*budget);
    *budget -= (end - start).min(limit);
    if end - start <= limit {
        return py_strip(&chars[start..end]);
    }
    py_strip(&chars[start..start + limit]) + TRUNCATED_SUFFIX
}

type Argument = (Option<String>, String);
type CallRecord = (String, usize, usize, usize, Vec<Argument>, Option<String>);

fn split_arguments(
    chars: &[char],
    tokens: &[Token],
    matches: &[Option<usize>],
    opening: usize,
    closing: usize,
    budget: &mut usize,
) -> Vec<Argument> {
    let mut output = Vec::new();
    if closing == opening + 1 {
        return output;
    }
    let mut parts = Vec::new();
    let (mut start, mut index) = (opening + 1, opening + 1);
    while index < closing {
        if let Some(matched) = matches[index] {
            index = matched + 1;
            continue;
        }
        if tokens[index].kind == Kind::Punctuation && tokens[index].value == "," {
            parts.push((start, index));
            start = index + 1;
        }
        index += 1;
    }
    parts.push((start, closing));
    for (mut first, last) in parts {
        if first >= last {
            continue;
        }
        let mut key = None;
        if first + 1 < last
            && tokens[first].kind == Kind::Identifier
            && tokens[first + 1].value == "="
        {
            key = Some(tokens[first].value.clone());
            first += 2;
        }
        if first < last {
            output.push((
                key,
                argument_text(chars, tokens[first].start, tokens[last - 1].end, budget),
            ));
        }
    }
    output
}

fn scan(chars: &[char]) -> Result<Vec<CallRecord>, ScanError> {
    let tokens = tokenize(chars)?;
    let matches = bracket_matches(&tokens)?;
    let mut calls = Vec::new();
    let mut budget = MAX_TOTAL_ARGUMENT_CHARS;
    let mut open_calls: Vec<(usize, String)> = Vec::new();
    for index in 0..tokens.len().saturating_sub(1) {
        while open_calls
            .last()
            .is_some_and(|(closing, _)| *closing < index)
        {
            open_calls.pop();
        }
        let (token, following) = (&tokens[index], &tokens[index + 1]);
        if token.kind != Kind::Identifier
            || following.kind != Kind::Punctuation
            || following.value != "("
        {
            continue;
        }
        let closing = matches[index + 1].expect("validated brackets");
        let mut name = token.value.clone();
        if index >= 2 && matches!(tokens[index - 1].value.as_str(), "::" | ":::") {
            name = format!("{}::{}", tokens[index - 2].value, name);
        }
        let parent = open_calls.last().map(|(_, parent)| parent.clone());
        calls.push((
            name.clone(),
            token.start,
            tokens[closing].end,
            token.line,
            split_arguments(chars, &tokens, &matches, index + 1, closing, &mut budget),
            parent,
        ));
        open_calls.push((closing, name));
    }
    Ok(calls)
}

/// Mirror of `visualization_analysis._scan_calls_python`.
///
/// Returns call tuples `(name, start, end, line, ((key, text), ...), parent)` with
/// Python character offsets, `None` when the Python implementation must run, and
/// raises `ValueError(code, message)` for R syntax errors.
#[pyfunction]
fn scan_calls<'py>(py: Python<'py>, source: String) -> PyResult<Option<Bound<'py, PyList>>> {
    if source.len() > 256 << 10 {
        return Err(PyValueError::new_err((
            "input_too_large",
            "R source exceeds 256 KiB",
        )));
    }
    let result = py.detach(move || {
        let chars: Vec<char> = source.chars().collect();
        scan(&chars)
    });
    let calls = match result {
        Ok(calls) => calls,
        Err(ScanError::NeedsPython) => return Ok(None),
        Err(ScanError::Syntax(message)) => {
            return Err(PyValueError::new_err(("invalid_r_syntax", message)));
        }
    };
    // Build tuples directly so Python can wrap them with NamedTuple._make.
    let records = calls
        .into_iter()
        .map(|(name, start, end, line, arguments, parent)| {
            let arguments = PyTuple::new(py, arguments)?;
            (name, start, end, line, arguments, parent).into_pyobject(py)
        })
        .collect::<PyResult<Vec<_>>>()?;
    Ok(Some(PyList::new(py, records)?))
}

struct Entry {
    name: String,
    folded: String,
    name_words: Vec<String>,
    title_folded: String,
    title_words: Vec<String>,
    name_chars: usize,
}

/// Python `re.findall(r"[0-9a-z]+", text)` on already case-folded text.
fn words(text: &str) -> Vec<String> {
    text.split(|c: char| !(c.is_ascii_digit() || c.is_ascii_lowercase()))
        .filter(|word| !word.is_empty())
        .map(String::from)
        .collect()
}

fn term_score(term: &str, entry: &Entry) -> u32 {
    let long = term.chars().count() >= 3;
    if entry.folded == term {
        return 100;
    }
    if entry.folded.starts_with(term) {
        return 40;
    }
    if entry.name_words.iter().any(|word| word == term) {
        return 30;
    }
    if entry.name_words.iter().any(|word| word.starts_with(term)) {
        return 20;
    }
    if long && entry.folded.contains(term) {
        return 10;
    }
    let plain_word = term
        .bytes()
        .all(|b| b.is_ascii_digit() || b.is_ascii_lowercase());
    if !plain_word {
        return if long && entry.title_folded.contains(term) {
            6
        } else {
            0
        };
    }
    if entry.title_words.iter().any(|word| word == term) {
        return 8;
    }
    if long && entry.title_words.iter().any(|word| word.starts_with(term)) {
        return 4;
    }
    0
}

/// Mirror of `providers.base.PackageSearchIndex`; callers pass case-folded text.
#[pyclass(frozen)]
struct SearchIndex {
    entries: Vec<Entry>,
}

#[pymethods]
impl SearchIndex {
    /// `entries`: `(name, name.casefold(), (title or "").casefold())`.
    #[new]
    fn new(entries: Vec<(String, String, String)>) -> Self {
        let entries = entries
            .into_iter()
            .map(|(name, folded, title_folded)| {
                let mut name_words = words(&folded);
                name_words.sort();
                name_words.dedup();
                Entry {
                    name_chars: name.chars().count(),
                    name,
                    name_words,
                    title_words: words(&title_folded),
                    folded,
                    title_folded,
                }
            })
            .collect();
        SearchIndex { entries }
    }

    /// `terms`/`folded_query`: `" ".join(query.casefold().split())` and its split.
    fn search(&self, py: Python<'_>, terms: Vec<String>, folded_query: String) -> Vec<String> {
        py.detach(|| {
            let mut ranked: Vec<(i64, usize, &str, &str)> = Vec::new();
            'entries: for entry in &self.entries {
                let mut score: i64 = 0;
                for term in &terms {
                    let value = term_score(term, entry);
                    if value == 0 {
                        continue 'entries;
                    }
                    score += i64::from(value);
                }
                if entry.folded == folded_query {
                    score += 1000;
                }
                ranked.push((-score, entry.name_chars, &entry.folded, &entry.name));
            }
            ranked.sort_unstable();
            ranked.into_iter().map(|row| row.3.to_string()).collect()
        })
    }

    fn __len__(&self) -> usize {
        self.entries.len()
    }
}

#[pymodule]
fn cran_knowledge_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("ABI_VERSION", ABI_VERSION)?;
    module.add_function(wrap_pyfunction!(scan_calls, module)?)?;
    module.add_class::<SearchIndex>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scan_source(source: &str) -> Result<Vec<CallRecord>, ScanError> {
        scan(&source.chars().collect::<Vec<_>>())
    }

    #[test]
    fn namespace_literals_methods_and_imports_keep_exact_arguments() {
        let calls = scan_source(
            "export(select, \"données\")\nimportFrom(OtherPkg, delegated)\n\
             S3method(print, Widget)\nexportMethods(show)\n",
        )
        .unwrap();
        assert_eq!(calls.len(), 4);
        assert_eq!(calls[0].0, "export");
        assert_eq!(calls[0].4[1].1, "\"données\"");
        assert_eq!(calls[1].4[0].1, "OtherPkg");
        assert_eq!(calls[2].0, "S3method");
        assert_eq!(calls[3].0, "exportMethods");
        assert!(calls.iter().all(|call| call.5.is_none()));
    }

    #[test]
    fn dynamic_namespace_calls_are_not_executed_and_remain_visible() {
        let source = "if (TRUE) { export(hidden) }\nexport(get('dynamic'))";
        let calls = scan_source(source).unwrap();
        assert!(calls.iter().any(|call| call.0 == "if"));
        assert!(calls
            .iter()
            .any(|call| call.0 == "get" && call.5.as_deref() == Some("export")));
        let real = calls.iter().find(|call| call.0 == "export").unwrap();
        let chars: Vec<char> = source.chars().collect();
        assert_eq!(
            chars[real.1..real.2].iter().collect::<String>(),
            "export(hidden)"
        );
    }

    #[test]
    fn malformed_input_returns_syntax_error_and_unicode_code_defers() {
        for source in ["export(", "export('unclosed)", "export(a])"] {
            assert!(matches!(scan_source(source), Err(ScanError::Syntax(_))));
        }
        assert!(matches!(
            scan_source("export(données)"),
            Err(ScanError::NeedsPython)
        ));
    }

    #[test]
    fn namespace_scanning_is_deterministic_and_argument_copies_are_bounded() {
        let source = format!("export(\"{}\")", "a".repeat(4000));
        let a = scan_source(&source).unwrap();
        let b = scan_source(&source).unwrap();
        assert_eq!(a, b);
        assert!(a[0].4[0].1.chars().count() < 2100);
        assert!(a[0].4[0].1.ends_with(TRUNCATED_SUFFIX));
    }
}
