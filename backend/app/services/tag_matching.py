"""Deterministic (non-AI) tag duplicate detection.

Catches near-duplicates that are unambiguous from spelling alone — hyphenation
variants ("e-mail" / "email") and plural/singular pairs ("ai-agent" /
"ai-agents") — so they never need an LLM call to resolve. Semantic synonyms
("ml" / "machine-learning") are out of scope here; those still go through the
AI-assisted /tags/suggest-merges flow.

The plural rule requires the singular stem to be at least 4 characters. Below
that, "add an s" can land on an unrelated word ("io" -> "ios" is I/O vs
Apple's OS, not a plural), so short tags are left alone. Even above that
length, a plural-shaped pair can be two unrelated words rather than a true
singular/plural ("canva" the design app vs "canvas") — hyphen-equivalence
alone (same characters, just re-hyphenated) has no such failure mode, since
it's the identical word either way. Callers that act automatically without a
human in the loop (canonicalize_tag) only trust the plural rule when one of
the two tags is a compound (hyphenated) one, where an unrelated-word
collision essentially doesn't happen; the reviewed suggestion list
(build_mechanical_groups) surfaces the plural rule for single-word tags too,
since a human checks it before anything is applied.
"""

import time
from typing import Dict, List, Optional, Tuple

_MIN_SINGULAR_STEM_LEN = 4


def _hyphen_key(tag: str) -> str:
    """Same characters, hyphens aside — merging on this alone is always safe."""
    return tag.strip().lower().replace("-", "")


def mechanical_key(tag: str) -> str:
    """Canonical key such that two tags sharing it are candidates to merge."""
    hyphenless = _hyphen_key(tag)
    if hyphenless.endswith("es") and len(hyphenless) - 2 >= _MIN_SINGULAR_STEM_LEN:
        return hyphenless[:-2]
    if (
        hyphenless.endswith("s")
        and not hyphenless.endswith("ss")
        and len(hyphenless) - 1 >= _MIN_SINGULAR_STEM_LEN
    ):
        return hyphenless[:-1]
    return hyphenless


def _bucket_by_key(tag_counts: Dict[str, int]) -> Dict[str, List[Tuple[str, int]]]:
    buckets: Dict[str, List[Tuple[str, int]]] = {}
    for tag, count in tag_counts.items():
        buckets.setdefault(mechanical_key(tag), []).append((tag, count))
    return buckets


def build_key_to_canonical(tag_counts: Dict[str, int]) -> Dict[str, str]:
    """Map every mechanical key to the most-used existing spelling for it
    (every key gets an entry, including singleton buckets)."""
    key_to_canonical: Dict[str, str] = {}
    for key, members in _bucket_by_key(tag_counts).items():
        key_to_canonical[key] = sorted(members, key=lambda tc: (-tc[1], tc[0]))[0][0]
    return key_to_canonical


def build_mechanical_canonical_map(tag_counts: Dict[str, int]) -> Dict[str, str]:
    """Map each non-canonical existing tag to its canonical spelling.

    Only includes tags that have a mechanical duplicate already in
    *tag_counts* — used for backfilling merges across the current corpus.
    """
    canonical_map: Dict[str, str] = {}
    for members in _bucket_by_key(tag_counts).values():
        if len(members) < 2:
            continue
        canonical = sorted(members, key=lambda tc: (-tc[1], tc[0]))[0][0]
        for tag, _count in members:
            if tag != canonical:
                canonical_map[tag] = canonical
    return canonical_map


def build_mechanical_groups(tag_counts: Dict[str, int]) -> List[dict]:
    """Same grouping as build_mechanical_canonical_map, shaped like the
    suggest-merges response: [{"canonical": tag, "merge": [tag, ...]}]."""
    canonical_map = build_mechanical_canonical_map(tag_counts)
    grouped: Dict[str, List[str]] = {}
    for source, canonical in canonical_map.items():
        grouped.setdefault(canonical, []).append(source)
    return [
        {"canonical": canonical, "merge": sorted(sources)}
        for canonical, sources in sorted(grouped.items())
    ]


# ---------------------------------------------------------------------------
# Write-time canonicalization (prevention) — cached lookup of the existing
# corpus so newly-generated tags snap to the established spelling instead of
# creating a fresh mechanical duplicate.
# ---------------------------------------------------------------------------

_key_to_canonical_cache: Optional[Dict[str, str]] = None
_key_to_canonical_cache_time: float = 0
_CANONICAL_MAP_TTL = 3600  # 1 hour — matches the popular-tags prompt cache


def clear_canonical_map_cache() -> None:
    global _key_to_canonical_cache, _key_to_canonical_cache_time
    _key_to_canonical_cache = None
    _key_to_canonical_cache_time = 0


def _get_key_to_canonical(db) -> Dict[str, str]:
    global _key_to_canonical_cache, _key_to_canonical_cache_time

    now = time.monotonic()
    if (
        _key_to_canonical_cache is not None
        and (now - _key_to_canonical_cache_time) < _CANONICAL_MAP_TTL
    ):
        return _key_to_canonical_cache

    from sqlalchemy import func

    from app.models import PostTag

    rows = (
        db.query(PostTag.tag, func.count(PostTag.post_id))
        .group_by(PostTag.tag)
        .all()
    )
    tag_counts = {tag: count for tag, count in rows}

    _key_to_canonical_cache = build_key_to_canonical(tag_counts)
    _key_to_canonical_cache_time = now
    return _key_to_canonical_cache


def canonicalize_tag(db, tag: str) -> str:
    """Rewrite *tag* to its established spelling if a mechanical duplicate
    already exists in the corpus; otherwise return it unchanged.

    Applies automatically with no review, so it only acts on matches with no
    plausible false positive: hyphen-equivalence always qualifies, and the
    plural rule only when *tag* or the candidate canonical is a compound
    (hyphenated) tag — see module docstring for why plain single-word
    plurals ("canva" vs "canvas") are excluded here.
    """
    key = mechanical_key(tag)
    canonical = _get_key_to_canonical(db).get(key)
    if not canonical or canonical == tag:
        return tag

    if _hyphen_key(tag) == _hyphen_key(canonical):
        return canonical  # pure hyphenation difference — always safe
    if "-" in tag or "-" in canonical:
        return canonical  # plural of a compound tag — safe in practice
    return tag
