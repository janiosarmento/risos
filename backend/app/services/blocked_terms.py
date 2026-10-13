"""
Blocked-term matching against post titles.

Shared by the post list (is_blocked / Blocked view), suggestions, and the
summary pipeline, which skips blocked posts so they never cost an LLM call.
"""

import re


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


def title_matches_term(title_lower: str, term: str) -> bool:
    """
    Check if a title matches a blocked term.

    Without *: whole-word match ("ford" won't match "affordable").
    With *: substring match per segment, joined by .*?
    Handles terms with non-word chars like [review].
    """
    if "*" not in term:
        escaped = re.escape(term)
        lb = _word_boundary(escaped, "start")
        rb = _word_boundary(escaped, "end")
        pattern = lb + escaped + rb
        return bool(re.search(pattern, title_lower))
    parts = [re.escape(seg) for seg in term.split("*") if seg]
    if not parts:
        return False
    # Add word boundaries to first/last segments
    pattern = ".*?".join(parts)
    if not term.startswith("*"):
        pattern = _word_boundary(parts[0], "start") + pattern
    if not term.endswith("*"):
        pattern = pattern + _word_boundary(parts[-1], "end")
    return bool(re.search(pattern, title_lower))


def title_is_blocked(title: str | None, terms: list) -> bool:
    """True if *title* matches any of the blocked *terms*."""
    title_lower = (title or "").lower()
    return any(title_matches_term(title_lower, term) for term in terms)
