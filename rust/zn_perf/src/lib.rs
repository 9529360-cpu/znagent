//! PERF-1 pilot: Rust port of the skill-routing cue matcher.
//!
//! This mirrors ``zn_agent.core.skill_routing._best_cue_for_header``
//! (plus its helpers ``_cue_occurs``) over *already-normalized* strings:
//! Python owns NFKC/casefold normalization (cheap, once per call); Rust owns
//! the hot part -- cue n-gram generation plus the per-cue occurrence test
//! that dominates ``match_skill_headers`` CPU time (regex compile+search per
//! cue in the Python version).
//!
//! Behavior contract (must stay identical to the Python original):
//! * cue set = {name, description} + word n-grams (width 4..2) of the
//!   description + CJK char n-grams (length 8..4) of CJK words;
//! * occurrence rules of ``_cue_occurs``: exact equality wins; cues shorter
//!   than 2 chars never occur; CJK cues are plain substrings; cues with
//!   ASCII alphanumerics need non-``[a-z0-9_]`` boundaries (and single words
//!   need >= 12 chars); everything else needs non-``\w`` boundaries;
//! * longest occurring cue wins; ``""`` when nothing occurs.
//!
//! Tie-breaking note: the Python version iterates a ``set``, so ties among
//! equal-length cues are hash-order nondeterministic *across processes*.
//! This port iterates in deterministic insertion order instead -- strictly
//! more predictable, and no reliable test can depend on the old order.

use pyo3::prelude::*;
use std::collections::HashSet;

fn is_cjk(c: char) -> bool {
    ('\u{4e00}'..='\u{9fff}').contains(&c)
}

fn contains_cjk(s: &str) -> bool {
    s.chars().any(is_cjk)
}

fn contains_ascii_alnum(s: &str) -> bool {
    s.bytes().any(|b| b.is_ascii_alphanumeric())
}

/// Approximation of Python ``re`` ``\w`` (Unicode): alphanumeric or underscore.
fn is_word_char(c: char) -> bool {
    c == '_' || c.is_alphanumeric()
}

/// Every occurrence of `cue` in `query` whose immediate neighbours are not
/// boundary characters (Python ``(?<!B)cue(?!B)`` semantics).
fn bounded_contains(query: &str, cue: &str, is_boundary: impl Fn(char) -> bool + Copy) -> bool {
    let mut start = 0usize;
    while start <= query.len() {
        match query[start..].find(cue) {
            Some(rel) => {
                let s = start + rel;
                let e = s + cue.len();
                let before_ok = query[..s]
                    .chars()
                    .next_back()
                    .map_or(true, |c| !is_boundary(c));
                let after_ok = query[e..]
                    .chars()
                    .next()
                    .map_or(true, |c| !is_boundary(c));
                if before_ok && after_ok {
                    return true;
                }
                // Advance one char so overlapping occurrences are still tried
                // (mirrors the regex engine scanning every start position).
                let step = query[s..].chars().next().map_or(1, |c| c.len_utf8());
                start = s + step;
            }
            None => return false,
        }
    }
    false
}

fn cue_occurs(query: &str, cue: &str) -> bool {
    if query.is_empty() || cue.is_empty() {
        return false;
    }
    if query == cue {
        return true;
    }
    if cue.chars().count() < 2 {
        return false;
    }
    if contains_cjk(cue) {
        return query.contains(cue);
    }
    if contains_ascii_alnum(cue) {
        // Generic one-word cues are not semantic matches; require a phrase
        // or a long-enough token to avoid ambient activation.
        if !cue.contains(' ') && cue.chars().count() < 12 {
            return false;
        }
        return bounded_contains(query, cue, |c| matches!(c, 'a'..='z' | '0'..='9' | '_'));
    }
    bounded_contains(query, cue, is_word_char)
}

fn build_cues(normalized_name: &str, normalized_description: &str) -> Vec<String> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut cues: Vec<String> = Vec::new();
    let mut push = |s: String| {
        if seen.insert(s.clone()) {
            cues.push(s);
        }
    };
    push(normalized_name.to_string());
    push(normalized_description.to_string());

    let words: Vec<&str> = normalized_description.split_whitespace().collect();
    let n = words.len();
    let max_width = n.min(4);
    // Python: for width in range(min(4, len(words)), 1, -1)
    for width in (2..=max_width).rev() {
        for i in 0..=(n - width) {
            push(words[i..i + width].join(" "));
        }
    }
    for word in &words {
        if contains_cjk(word) {
            let chars: Vec<char> = word.chars().collect();
            let m = chars.len();
            let max_len = m.min(8);
            // Python: for length in range(min(8, len(word)), 3, -1)
            for length in (4..=max_len).rev() {
                for i in 0..=(m - length) {
                    push(chars[i..i + length].iter().collect());
                }
            }
        }
    }
    cues
}

fn best_cue(normalized_query: &str, normalized_name: &str, normalized_description: &str) -> String {
    let mut best = String::new();
    let mut best_len = 0usize;
    for cue in build_cues(normalized_name, normalized_description) {
        // Length check first: same outcome as the Python
        // `_cue_occurs(...) and len(cue) > len(best)`, fewer occurrence tests.
        let clen = cue.chars().count();
        if clen > best_len && cue_occurs(normalized_query, &cue) {
            best_len = clen;
            best = cue;
        }
    }
    best
}

/// Longest cue of one skill header occurring in the normalized query.
///
/// All three inputs must already be ``_normalize``d (NFKC + casefold +
/// ``[\W_]+`` collapsed), exactly as ``_best_cue_for_header`` receives them.
/// Returns ``""`` when no cue occurs.
#[pyfunction]
fn best_cue_for_header(
    normalized_query: &str,
    normalized_name: &str,
    normalized_description: &str,
) -> String {
    best_cue(normalized_query, normalized_name, normalized_description)
}

#[pymodule]
fn zn_perf_ext(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(best_cue_for_header, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_equality_wins() {
        assert!(cue_occurs("abc", "abc"));
    }

    #[test]
    fn short_cues_never_occur() {
        assert!(!cue_occurs("abc", "a"));
        // exact equality is checked before the length rule (mirrors Python)
        assert!(cue_occurs("a", "a"));
        assert!(!cue_occurs("ab", "a"));
    }

    #[test]
    fn cjk_is_plain_substring() {
        assert!(cue_occurs("帮我做中文任务管理", "中文任务管理"));
        assert!(!cue_occurs("帮我做英文任务管理", "中文任务管理"));
    }

    #[test]
    fn ascii_boundary_rules() {
        // "web research" occurs with word boundaries
        assert!(cue_occurs("do multi-source web research now", "web research"));
        // partial word does not count
        assert!(!cue_occurs("do web researches now", "web research"));
        // single short word is not a semantic match
        assert!(!cue_occurs("managing tasks", "managing"));
        // single long word (>=12) is allowed with boundaries
        assert!(cue_occurs("run containerization now", "containerization"));
        assert!(!cue_occurs("run hypercontainerization now", "containerization"));
    }

    #[test]
    fn longest_cue_wins() {
        let best = best_cue(
            "do multi source web research and managing tasks",
            "deep research",
            "use when doing multi source web research",
        );
        assert_eq!(best, "multi source web research");
    }

    #[test]
    fn no_cue_gives_empty() {
        assert_eq!(best_cue("hello world", "some skill", "does things"), "");
    }

    #[test]
    fn empty_inputs_give_empty() {
        assert_eq!(best_cue("", "name", "desc"), "");
        assert_eq!(best_cue("query", "", ""), "");
    }
}
