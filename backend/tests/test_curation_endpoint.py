"""Tests for the curation endpoint's two-pass orchestration.

Covers the parts that are not the clustering itself: that posts nobody
could be covering never reach the model, that the model's answer is merged
back without trusting it blindly, and that a repeat run is served from the
memo table instead of calling out again. The LLM is stubbed throughout — no
network.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.ai._api as ai_api
from app.database import Base
from app.models import CurationCache, Post, PostTag
from app.routes.posts import CurateRequest, curate_starred


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_post(db, post_id: int, title: str, tags: list[str]) -> None:
    db.add(Post(id=post_id, feed_id=1, title=title, is_starred=True))
    for tag in tags:
        db.add(PostTag(post_id=post_id, tag=tag))


def _stub_llm(monkeypatch, response: dict, calls: list):
    async def fake_call(system_prompt, user_prompt, **kwargs):
        calls.append({"system": system_prompt, "user": user_prompt, **kwargs})
        return response

    monkeypatch.setattr(ai_api, "call_llm_json", fake_call)


@pytest.mark.asyncio
async def test_no_starred_posts_returns_empty(db):
    result = await curate_starred(CurateRequest(), db=db, user={})

    assert result["total_posts"] == 0
    assert result["analysis"]["essential"] == []


@pytest.mark.asyncio
async def test_nothing_overlaps_means_no_llm_call(db, monkeypatch):
    calls: list = []
    _stub_llm(monkeypatch, {"decisions": []}, calls)
    _add_post(db, 1, "Gardening", ["tomatoes", "compost"])
    _add_post(db, 2, "Rust async", ["rust", "tokio"])
    db.commit()

    result = await curate_starred(CurateRequest(), db=db, user={})

    assert calls == []  # the whole point: no model round-trip
    assert {e["post_id"] for e in result["analysis"]["essential"]} == {1, 2}
    assert result["analysis"]["redundant"] == []


@pytest.mark.asyncio
async def test_only_clustered_posts_are_sent_to_the_model(db, monkeypatch):
    calls: list = []
    _stub_llm(
        monkeypatch,
        {"decisions": [{"post_id": 2, "verdict": "redundant", "covered_by": [1],
                        "reason": "covered by 1"}]},
        calls,
    )
    _add_post(db, 1, "SPF explained", ["spf", "dkim"])
    _add_post(db, 2, "SPF syntax", ["spf", "dkim"])
    _add_post(db, 3, "Unrelated gardening", ["tomatoes", "compost"])
    db.commit()

    result = await curate_starred(CurateRequest(), db=db, user={})

    assert len(calls) == 1
    prompt = calls[0]["user"]
    assert "1 |" in prompt and "2 |" in prompt
    assert "gardening" not in prompt.lower()  # never reached the model

    redundant = result["analysis"]["redundant"]
    assert [e["post_id"] for e in redundant] == [2]
    assert redundant[0]["covered_by"] == [1]
    # The ungrouped post is kept, decided locally.
    assert 3 in {e["post_id"] for e in result["analysis"]["essential"]}


@pytest.mark.asyncio
async def test_hallucinated_and_duplicate_ids_are_discarded(db, monkeypatch):
    calls: list = []
    _stub_llm(
        monkeypatch,
        {
            "decisions": [
                {"post_id": 2, "verdict": "redundant", "covered_by": [1, 999]},
                {"post_id": 2, "verdict": "essential"},  # duplicate, ignored
                {"post_id": 12345, "verdict": "redundant"},  # never existed
            ]
        },
        calls,
    )
    _add_post(db, 1, "SPF explained", ["spf", "dkim"])
    _add_post(db, 2, "SPF syntax", ["spf", "dkim"])
    db.commit()

    result = await curate_starred(CurateRequest(), db=db, user={})

    analysis = result["analysis"]
    all_ids = [
        e["post_id"]
        for key in ("essential", "redundant", "keep_if_interested")
        for e in analysis[key]
    ]
    assert sorted(all_ids) == [1, 2]  # invented id dropped, no duplicates
    # An id that is not in scope cannot justify dropping something.
    assert analysis["redundant"][0]["covered_by"] == [1]


@pytest.mark.asyncio
async def test_post_the_model_ignored_is_kept(db, monkeypatch):
    # Silence is not grounds for telling someone to drop an article.
    calls: list = []
    _stub_llm(monkeypatch, {"decisions": []}, calls)
    _add_post(db, 1, "SPF explained", ["spf", "dkim"])
    _add_post(db, 2, "SPF syntax", ["spf", "dkim"])
    db.commit()

    result = await curate_starred(CurateRequest(), db=db, user={})

    assert len(calls) == 1
    assert sorted(e["post_id"] for e in result["analysis"]["essential"]) == [1, 2]
    assert result["analysis"]["redundant"] == []


@pytest.mark.asyncio
async def test_second_run_is_served_from_cache(db, monkeypatch):
    calls: list = []
    _stub_llm(
        monkeypatch,
        {"decisions": [{"post_id": 2, "verdict": "redundant", "covered_by": [1]}]},
        calls,
    )
    _add_post(db, 1, "SPF explained", ["spf", "dkim"])
    _add_post(db, 2, "SPF syntax", ["spf", "dkim"])
    db.commit()

    first = await curate_starred(CurateRequest(), db=db, user={})
    second = await curate_starred(CurateRequest(), db=db, user={})

    assert len(calls) == 1  # not called again
    assert first["analysis"] == second["analysis"]
    assert db.query(CurationCache).count() == 1


@pytest.mark.asyncio
async def test_changing_the_algorithm_invalidates_the_cache(db, monkeypatch):
    # Otherwise a scoring fix would keep serving the answers it was meant
    # to correct, for exactly the libraries that had already been curated.
    import app.routes.posts as posts_module

    calls: list = []
    _stub_llm(monkeypatch, {"decisions": []}, calls)
    _add_post(db, 1, "SPF explained", ["spf", "dkim"])
    _add_post(db, 2, "SPF syntax", ["spf", "dkim"])
    db.commit()

    await curate_starred(CurateRequest(), db=db, user={})
    monkeypatch.setattr(
        posts_module, "CURATION_ALGO_VERSION", posts_module.CURATION_ALGO_VERSION + 1
    )
    await curate_starred(CurateRequest(), db=db, user={})

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_starring_something_new_invalidates_the_cache(db, monkeypatch):
    calls: list = []
    _stub_llm(
        monkeypatch,
        {"decisions": [{"post_id": 2, "verdict": "redundant", "covered_by": [1]}]},
        calls,
    )
    _add_post(db, 1, "SPF explained", ["spf", "dkim"])
    _add_post(db, 2, "SPF syntax", ["spf", "dkim"])
    db.commit()
    await curate_starred(CurateRequest(), db=db, user={})

    # The set of posts in scope changes, so the memo key changes with it.
    _add_post(db, 3, "DMARC explained", ["spf", "dkim"])
    db.commit()
    result = await curate_starred(CurateRequest(), db=db, user={})

    assert len(calls) == 2
    assert result["total_posts"] == 3
