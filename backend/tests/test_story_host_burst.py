from datetime import datetime, timedelta

from app.services.stories import StoryPost, group_stories

T0 = datetime(2026, 10, 1, 19, 24)
TAGS = {1: {"ai-agent", "open-source"}, 2: {"ai-agent", "storage"}}
IDF = {"ai-agent": 1.0, "open-source": 1.0, "storage": 1.0}


def _posts(gap, host_b="blog.example.com", feed_b=2):
    return [
        StoryPost(1, 2, T0, "Pi 1.0", "https://blog.example.com/pi-1-0/"),
        StoryPost(2, feed_b, T0 + gap, "Pi Durable", f"https://{host_b}/pi-durable/"),
    ]


def test_same_host_burst_groups():
    groups = group_stories(_posts(timedelta(minutes=8)), TAGS, IDF)
    assert [sorted(g) for g in groups] == [[1, 2]]


def test_same_host_far_apart_does_not_group():
    assert group_stories(_posts(timedelta(hours=5)), TAGS, IDF) == []


def test_different_host_does_not_group():
    posts = _posts(timedelta(minutes=8), host_b="other.example.org")
    assert group_stories(posts, TAGS, IDF) == []


def test_different_feed_does_not_group():
    assert group_stories(_posts(timedelta(minutes=8), feed_b=3), TAGS, IDF) == []


def test_busy_host_is_ignored():
    posts = [
        StoryPost(
            i,
            2,
            T0 + timedelta(minutes=i),
            f"Story {i}",
            f"https://news.example.com/{i}",
        )
        for i in range(1, 5)
    ]
    tags = {i: {"ai-agent"} for i in range(1, 5)}
    assert group_stories(posts, tags, IDF) == []
