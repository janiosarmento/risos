"""
Blocked-term matching against post titles.

Shared by the post list (is_blocked / Blocked view), suggestions, and the
summary pipeline, which skips blocked posts so they never cost an LLM call.
"""

import re
from functools import lru_cache


def _word_boundary(escaped: str, side: str) -> str:
    """Return appropriate boundary anchor for start/end of an escaped pattern.

    \b only works between \\w and \\W chars.  If the pattern edge is a
    non-word char (like '[' or '$'), we only need a boundary on the
    word-char side to prevent partial word matches.  The non-word char
    itself already breaks any word, so no boundary needed on that side.
    """
    if side == "start":
        ch = re.sub(r"\\(.)", r"\1", escaped[:1])  # un-escape first char
        if re.match(r"\w", ch):
            return r"\b"
        return r"(?<!\w)"
    else:
        ch = re.sub(r"\\(.)", r"\1", escaped[-1:])  # un-escape last char
        if re.match(r"\w", ch):
            return r"\b"
        return ""  # non-word char at end — no boundary needed


@lru_cache(maxsize=4096)
def _term_pattern(term: str) -> str | None:
    """Regex source for one blocked term, or None if it can never match.

    Without *: whole-word match ("ford" won't match "affordable").
    With *: substring match per segment, joined by .*?
    Handles terms with non-word chars like [review].
    """
    if "*" not in term:
        escaped = re.escape(term)
        lb = _word_boundary(escaped, "start")
        rb = _word_boundary(escaped, "end")
        return lb + escaped + rb
    parts = [re.escape(seg) for seg in term.split("*") if seg]
    if not parts:
        return None
    # Add word boundaries to first/last segments
    pattern = ".*?".join(parts)
    if not term.startswith("*"):
        pattern = _word_boundary(parts[0], "start") + pattern
    if not term.endswith("*"):
        pattern = pattern + _word_boundary(parts[-1], "end")
    return pattern


@lru_cache(maxsize=4096)
def _term_regex(term: str) -> re.Pattern | None:
    pattern = _term_pattern(term)
    return re.compile(pattern) if pattern is not None else None


@lru_cache(maxsize=8)
def _terms_regex(terms: tuple[str, ...]) -> re.Pattern | None:
    """One alternation over every term, so a title is scanned once.

    Hundreds of terms against every unread title is on the post list's hot
    path; matching them one by one was most of that request's time.
    """
    patterns = [p for p in map(_term_pattern, terms) if p is not None]
    if not patterns:
        return None
    return re.compile("|".join(f"(?:{p})" for p in patterns))


def title_matches_term(title_lower: str, term: str) -> bool:
    """Check if a title matches one blocked term (see _term_pattern)."""
    regex = _term_regex(term)
    return bool(regex and regex.search(title_lower))


def title_is_blocked(title: str | None, terms: list) -> bool:
    """True if *title* matches any of the blocked *terms*."""
    if not terms:
        return False
    regex = _terms_regex(tuple(terms))
    return bool(regex and regex.search((title or "").lower()))
