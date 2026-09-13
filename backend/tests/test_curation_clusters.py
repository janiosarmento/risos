"""Tests for the local (non-LLM) curation clustering.

The whole point of this pass is to answer "which saved articles could
possibly be covering the same ground?" without a model, so it is exercised
here against a real SQLite database built in memory — no network, no LLM.

The thresholds it applies are the subtle part: they have to survive the fact
that a real library's most common tags are near-universal ("2026" was on a
fifth of the corpus this was tuned against) while the tags that actually
signal overlap sit in the long tail.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Post, PostTag
from app.services.curation import find_redundancy_clusters


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_post(db, post_id: int, tags: list[str], *, starred: bool = True) -> None:
    db.add(Post(id=post_id, feed_id=1, title=f"post {post_id}", is_starred=starred))
    for tag in tags:
        db.add(PostTag(post_id=post_id, tag=tag))


def _bulk_noise(db, start_id: int, count: int, tag: str) -> None:
    """Posts that exist only to make `tag` common across the corpus."""
    for i in range(count):
        _add_post(db, start_id + i, [tag], starred=False)


def test_no_tags_means_no_clusters(db):
    _add_post(db, 1, [])
    _add_post(db, 2, [])
    db.commit()

    clusters, diag = find_redundancy_clusters(db, [1, 2])

    assert clusters == []
    assert "no tags" in diag["reason"]


def test_single_post_is_never_a_cluster(db):
    _add_post(db, 1, ["spf", "dkim"])
    db.commit()

    clusters, _ = find_redundancy_clusters(db, [1])

    assert clusters == []


def test_posts_sharing_rare_tags_cluster_together(db):
    _add_post(db, 1, ["spf", "dkim", "dmarc"])
    _add_post(db, 2, ["spf", "dkim", "dmarc"])
    db.commit()

    clusters, _ = find_redundancy_clusters(db, [1, 2])

    assert len(clusters) == 1
    assert clusters[0]["post_ids"] == [1, 2]
    assert set(clusters[0]["shared_tags"]) == {"spf", "dkim", "dmarc"}


def test_one_shared_tag_is_not_enough(db):
    # A single tag in common is a coincidence, not a sign of overlap.
    _add_post(db, 1, ["spf", "postfix"])
    _add_post(db, 2, ["spf", "kubernetes"])
    db.commit()

    clusters, _ = find_redundancy_clusters(db, [1, 2])

    assert clusters == []


def test_generic_tags_do_not_create_clusters(db):
    # Two posts sharing only near-universal tags are not related in any
    # useful sense — this is the case that made raw shared-tag counts useless
    # on a real library. Note both posts here have *identical* tag sets, so
    # similarity alone would call them a perfect match; what saves it is that
    # a tag on half the corpus never puts a pair up for scoring at all.
    _bulk_noise(db, 1000, 400, "2026")
    _bulk_noise(db, 2000, 400, "technology")
    _add_post(db, 1, ["2026", "technology"])
    _add_post(db, 2, ["2026", "technology"])
    db.commit()

    clusters, _ = find_redundancy_clusters(db, [1, 2])

    assert clusters == []


def test_a_specific_tag_outweighs_a_common_one(db):
    # The failure this replaces: a fixed "too common" cutoff threw away tags
    # like `malware` (0.8% of a real corpus) and scored an article saved
    # twice at zero. Rarity has to be a gradient, not a cliff.
    from app.services.curation import tag_idf

    assert tag_idf(500, 64_000) > 2.5 * tag_idf(12_000, 64_000)
    # A tag on every single post says nothing at all.
    assert tag_idf(64_000, 64_000) < 0.01
    # On a two-post library everything is "on half the corpus"; the weights
    # still have to be usable rather than collapsing to zero.
    assert tag_idf(2, 2) > 0
    # A frequency larger than the corpus (a stale count) must not go negative.
    assert tag_idf(80_000, 64_000) >= 0.0


def test_rare_tags_still_cluster_inside_a_large_corpus(db):
    # Same corpus as above, but now the pair also shares two specific tags.
    _bulk_noise(db, 1000, 400, "2026")
    _bulk_noise(db, 2000, 400, "technology")
    _add_post(db, 1, ["2026", "technology", "bufferbloat", "router"])
    _add_post(db, 2, ["2026", "technology", "bufferbloat", "router"])
    db.commit()

    clusters, _ = find_redundancy_clusters(db, [1, 2])

    assert len(clusters) == 1
    assert clusters[0]["post_ids"] == [1, 2]
    # The rare tags are what explain the grouping, so they are what the
    # adjudication prompt gets shown first.
    assert set(clusters[0]["shared_tags"][:2]) == {"bufferbloat", "router"}


def test_clusters_are_transitive(db):
    # A overlaps B, B overlaps C, A and C share nothing directly — all three
    # still belong in one group for adjudication.
    _add_post(db, 1, ["wireguard", "tailscale"])
    _add_post(db, 2, ["wireguard", "tailscale", "mesh-network", "vpn"])
    _add_post(db, 3, ["mesh-network", "vpn"])
    db.commit()

    clusters, _ = find_redundancy_clusters(db, [1, 2, 3])

    assert len(clusters) == 1
    assert clusters[0]["post_ids"] == [1, 2, 3]


def test_unrelated_groups_stay_separate(db):
    _add_post(db, 1, ["spf", "dkim"])
    _add_post(db, 2, ["spf", "dkim"])
    _add_post(db, 3, ["bufferbloat", "router"])
    _add_post(db, 4, ["bufferbloat", "router"])
    db.commit()

    clusters, diag = find_redundancy_clusters(db, [1, 2, 3, 4])

    assert sorted(c["post_ids"] for c in clusters) == [[1, 2], [3, 4]]
    assert diag["clusters"] == 2
    assert diag["posts_clustered"] == 4


def test_posts_outside_any_cluster_are_left_alone(db):
    _add_post(db, 1, ["spf", "dkim"])
    _add_post(db, 2, ["spf", "dkim"])
    _add_post(db, 3, ["gardening", "tomatoes"])
    db.commit()

    clusters, diag = find_redundancy_clusters(db, [1, 2, 3])

    clustered = {pid for c in clusters for pid in c["post_ids"]}
    assert clustered == {1, 2}
    assert 3 not in clustered
    assert diag["posts_in_scope"] == 3


def test_large_cluster_is_split_for_prompting(db):
    # Everything shares the same two rare tags, so they all connect; the
    # result must still be chopped into prompt-sized groups.
    from app.services.curation import MAX_CLUSTER_SIZE

    ids = list(range(1, MAX_CLUSTER_SIZE + 6))
    for pid in ids:
        _add_post(db, pid, ["nixos", "flakes"])
    db.commit()

    clusters, _ = find_redundancy_clusters(db, ids)

    assert len(clusters) > 1
    assert all(len(c["post_ids"]) <= MAX_CLUSTER_SIZE for c in clusters)
    # No post is lost or duplicated in the split.
    flat = [pid for c in clusters for pid in c["post_ids"]]
    assert sorted(flat) == ids
