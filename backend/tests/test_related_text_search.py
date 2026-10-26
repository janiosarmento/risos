"""Tests for the assistant's full-text search for related posts."""

from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import AISummary, Feed, Post, PostTag
from app.routes.posts import _keywords_from_title, _text_search_related

NOW = datetime(2026, 1, 1)


@pytest.fixture
def db(fts_engine):
    session = sessionmaker(bind=fts_engine)()
    session.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    session.commit()
    yield session
    session.close()


def _add(db, post_id, title, content=None, summary=None, tags=(), is_read=False):
    content_hash = f"hash-{post_id}"
    db.add(
        Post(
            id=post_id,
            feed_id=1,
            title=title,
            content=content,
            content_hash=content_hash,
            sort_date=NOW,
            is_read=is_read,
        )
    )
    if summary:
        _summarize(db, post_id, summary)
    for tag in tags:
        db.add(PostTag(post_id=post_id, tag=tag))
    db.commit()


def _summarize(db, post_id, summary):
    db.add(
        AISummary(
            content_hash=f"hash-{post_id}",
            summary_pt=summary,
            one_line_summary="",
        )
    )
    db.commit()


def _search(db, keywords, min_common_tags=0, limit=30, active_tags=(), **kwargs):
    options = dict(include_read=True, include_unread=True) | kwargs
    results = _text_search_related(
        db,
        post_id=1,
        keywords=keywords,
        active_tags=list(active_tags),
        limit=limit,
        min_common_tags=min_common_tags,
        **options,
    )
    return [r["id"] for r in results]


def test_keywords_match_whole_words_only(db):
    _add(db, 1, "Arc Browser ships tab sync")
    # "arc" only occurs inside "research", "search" and "March".
    _add(db, 2, "Research from March", summary="A search engine study.")

    assert _search(db, ["arc", "browser"]) == []


def test_more_matching_keywords_rank_higher(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "Browser market share report")
    _add(db, 3, "Arc Browser adds split view")

    assert _search(db, ["arc", "browser"]) == [3, 2]


def test_feed_excerpt_does_not_count_as_a_match(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "New release", content="Built by the Arc browser team.")

    assert _search(db, ["arc", "browser"]) == []


def test_ai_summary_counts_as_a_match(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "New release", summary="<p>Built by the Arc team.</p>")

    assert _search(db, ["arc", "browser"]) == [2]


def test_possessive_and_diacritics_match_base_word(db):
    _add(db, 1, "Café ships desktop")
    _add(db, 2, "Cafe's new desktop")

    assert _search(db, ["café", "desktop"]) == [2]


def test_hyphenated_keyword_matches_as_phrase(db):
    _add(db, 1, "SparkyOS debuts as an Arch-based distro")
    _add(db, 2, "Omarchy is an Arch-based distro")
    _add(db, 3, "Arch bridges are based on stone")

    assert _search(db, ["arch-based"]) == [2]


def test_common_tag_filter_and_limit(db):
    _add(db, 1, "Arc Browser ships tab sync", tags=("arc",))
    _add(db, 2, "Arc Browser adds split view")
    _add(db, 3, "Arc Browser adds profiles", tags=("arc",))
    _add(db, 4, "Arc Browser hits beta", tags=("arc",))

    found = _search(db, ["arc", "browser"], min_common_tags=1, active_tags=("arc",))
    assert sorted(found) == [3, 4]
    limited = _search(
        db, ["arc", "browser"], min_common_tags=1, active_tags=("arc",), limit=1
    )
    assert len(limited) == 1


def test_read_state_filters(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "Arc Browser adds split view", is_read=True)
    _add(db, 3, "Arc Browser adds profiles")

    assert _search(db, ["arc"], include_read=False) == [3]
    assert _search(db, ["arc"], include_unread=False) == [2]


def test_results_carry_read_state(db):
    # The assistant only decrements unread counters for posts that were
    # actually unread, so each result reports is_read and keep_unread.
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "Arc Browser adds split view", is_read=True)
    _add(db, 3, "Arc Browser adds profiles")
    db.get(Post, 3).keep_unread = True
    db.commit()

    results = _text_search_related(
        db,
        post_id=1,
        keywords=["arc"],
        active_tags=[],
        limit=30,
        min_common_tags=0,
        include_read=True,
        include_unread=True,
    )
    state = {r["id"]: (r["is_read"], r["keep_unread"]) for r in results}
    assert state == {2: (True, False), 3: (False, True)}


def test_index_follows_summary_writes(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "New release")
    assert _search(db, ["arc"]) == []

    _summarize(db, 2, "Built by the Arc team.")
    assert _search(db, ["arc"]) == [2]

    summary = db.query(AISummary).filter_by(content_hash="hash-2").one()
    summary.summary_pt = "Built by another team."
    db.commit()
    assert _search(db, ["arc"]) == []

    summary.summary_pt = "Built by the Arc team."
    db.commit()
    db.delete(summary)
    db.commit()
    assert _search(db, ["arc"]) == []


def test_index_follows_post_updates_and_deletes(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "New release")

    post = db.get(Post, 2)
    post.title = "Arc release"
    db.commit()
    assert _search(db, ["arc"]) == [2]

    db.delete(post)
    db.commit()
    assert _search(db, ["arc"]) == []


def test_single_generic_word_hits_are_dropped(db):
    keywords = ["bowel", "common", "disease", "multiple", "sclerosis", "treatment"]
    _add(db, 1, "Common multiple sclerosis treatment linked to bowel disease")
    _add(db, 2, "Why Common Lisp is the best programming language")
    _add(db, 3, "Multiple sclerosis drug raises bowel disease risk")
    # Unrelated filler, so the keywords are rare as in a real database.
    for post_id in range(10, 40):
        _add(db, post_id, f"Unrelated headline number {post_id}")

    assert _search(db, keywords) == [3]


def test_keywords_drop_possessive_suffix():
    assert _keywords_from_title("China’s Linux and Apple's desktop") == [
        "apple",
        "china",
        "desktop",
        "linux",
    ]
