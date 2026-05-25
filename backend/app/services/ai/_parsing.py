"""Parsing, validation, and tag normalization for the Cerebras client."""

import json
import logging
import re
from typing import List

from app.services.ai._constants import (
    MIN_CONTENT_LENGTH,
    SHORT_CONTENT_LENGTH,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Summary paragraph splitting
# ---------------------------------------------------------------------------

_ABBREVIATIONS = sorted(
    [
        "etc.", "vs.", "p.ex.",
        "Inc.", "Ltd.", "Corp.", "Co.",
        "Dr.", "Dra.", "Sr.", "Sra.", "Prof.", "Profa.", "Jr.",
        "i.e.", "e.g.",
        "U.S.", "U.K.", "O.J.",
        "EUA.", "nº.", "ed.", "vol.", "cap.",
    ],
    key=len,
    reverse=True,
)

_PLACEHOLDER = "\x00"

_ABBREV_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(abbr) for abbr in _ABBREVIATIONS) + r")"
)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÝÇ0-9])")


def split_into_paragraphs(summary: str) -> str:
    """Split a dense summary into paragraphs at sentence boundaries,
    preserving common abbreviations (vs., Dr., U.S., etc.)."""
    if not summary:
        return summary

    def _split_block(block: str) -> str:
        masked = _ABBREV_PATTERN.sub(
            lambda m: m.group(0).replace(".", _PLACEHOLDER), block
        )
        sentences = _SENTENCE_BOUNDARY.split(masked)
        return "\n\n".join(
            s.replace(_PLACEHOLDER, ".").strip()
            for s in sentences
            if s.strip()
        )

    # Process each existing paragraph independently
    return "\n\n".join(
        _split_block(p) for p in re.split(r"\n\s*\n", summary)
    )


# Tags too generic to be useful
GENERIC_TAGS = frozenset({"news", "article", "technology", "update", "post"})


# Patterns that indicate error/garbage pages (no real content)
GARBAGE_PATTERNS = [
    # GitHub session errors
    "reload to refresh your session",
    "you signed in with another tab",
    "you signed out in another tab",
    "you switched accounts on another tab",
    "you can't perform that action at this time",
    "octocat-spinner",
    # Common error pages
    "access denied",
    "403 forbidden",
    "404 not found",
    "500 internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "page not found",
    # Paywalls/login walls
    "subscribe to continue reading",
    "create an account to continue",
    "sign in to continue",
    "this content is for subscribers only",
    # Cookie/GDPR walls
    "we use cookies",
    "accept all cookies",
    "manage cookie preferences",
]


def is_garbage_content(content: str) -> bool:
    """
    Detect if content is an error/session/paywall page
    that should not be sent to AI.
    """
    if not content or len(content.strip()) < MIN_CONTENT_LENGTH:
        return True

    content_lower = content.lower()

    # Check for garbage patterns
    matches = sum(
        1 for pattern in GARBAGE_PATTERNS if pattern in content_lower
    )

    # If multiple patterns match or content is very short with one match
    if matches >= 2:
        return True
    if matches >= 1 and len(content.strip()) < SHORT_CONTENT_LENGTH:
        return True

    return False


def normalize_tag(tag: str) -> str:
    """
    Normalize a single tag: lowercase, hyphens for separators, collapse doubles.
    Returns empty string for invalid tags.
    """
    normalized = tag.lower().strip()
    normalized = normalized.replace(" ", "-").replace("_", "-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    normalized = normalized.strip("-")
    return normalized


def normalize_tags(raw_tags: list, max_tags: int = 15) -> List[str]:
    """
    Normalize and filter a list of raw tags from the model.
    Removes generic tags, empty tags, and single-char tags.
    """
    tags = []
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            if isinstance(tag, str):
                normalized = normalize_tag(tag)
                if (
                    normalized
                    and len(normalized) > 1
                    and normalized not in GENERIC_TAGS
                ):
                    tags.append(normalized)
    return tags[:max_tags]


def parse_json_response(content: str) -> dict:
    """
    Parse JSON response robustly.
    Handles markdown code blocks, incorrect escapes, etc.
    """

    # Remove markdown code blocks if present
    # Pattern: ```json ... ``` or ``` ... ```
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if code_block_match:
        content = code_block_match.group(1)

    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from within text
    json_start = content.find("{")
    json_end = content.rfind("}") + 1

    if json_start < 0 or json_end <= json_start:
        raise ValueError("JSON not found in response")

    json_str = content[json_start:json_end]

    # Try parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Try to fix common escape issues
    # Literal newlines inside strings
    json_str_fixed = json_str

    # Replace real newlines inside strings with \n
    # This is a hack but helps with some models
    def fix_string_newlines(match):
        s = match.group(0)
        # Replace real newlines with escape
        s = s.replace("\n", "\\n").replace("\r", "\\r")
        return s

    # Find JSON strings and fix
    json_str_fixed = re.sub(r'"[^"]*"', fix_string_newlines, json_str)

    try:
        return json.loads(json_str_fixed)
    except json.JSONDecodeError:
        pass

    # Last attempt: extract fields manually with regex
    summary_match = re.search(
        r'"summary_pt"\s*:\s*"((?:[^"\\]|\\.)*)"|"summary_pt"\s*:\s*"([^"]*)"',
        json_str,
        re.DOTALL,
    )
    one_line_match = re.search(
        r'"one_line_summary"\s*:\s*"((?:[^"\\]|\\.)*)"|"one_line_summary"\s*:\s*"([^"]*)"',
        json_str,
        re.DOTALL,
    )

    if summary_match and one_line_match:
        summary = summary_match.group(1) or summary_match.group(2) or ""
        one_line = one_line_match.group(1) or one_line_match.group(2) or ""
        # Decode basic escapes
        summary = (
            summary.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace('\\"', '"')
        )
        one_line = (
            one_line.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace('\\"', '"')
        )
        return {"summary_pt": summary, "one_line_summary": one_line}

    raise ValueError(f"Could not parse JSON: {json_str[:200]}...")
