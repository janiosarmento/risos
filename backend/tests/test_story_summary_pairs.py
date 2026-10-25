"""The prefix-filtered summary pairing must find exactly what checking every
pair would."""

import math
import random
from collections import Counter
from datetime import datetime, timedelta

import pytest

from app.services import stories
from app.services.stories import StoryPost, tokenize_summary

T0 = datetime(2026, 10, 1)


def _brute_force(by_id, summaries):
    """Every pair within MAX_GAP, scored the way the docstring defines it."""
    token_sets = {
        pid: toks
        for pid, text in summaries.items()
        if pid in by_id and (toks := tokenize_summary(text))
    }
    n = len(token_sets)
    df = Counter()
    for toks in token_sets.values():
        df.update(toks)
    idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
    weight = {pid: sum(idf[t] ** 2 for t in toks) for pid, toks in token_sets.items()}
    seed_cutoff = max(
        stories.SUMMARY_SEED_MIN_FREQ, int(n * stories.SUMMARY_SEED_MAX_RATIO)
    )
    found = {}
    ids = sorted(token_sets)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if abs(by_id[a].sort_date - by_id[b].sort_date) > stories.MAX_GAP:
                continue
            shared = token_sets[a] & token_sets[b]
            if not any(df[t] <= seed_cutoff for t in shared):
                continue
            score = sum(idf[t] ** 2 for t in shared) / min(weight[a], weight[b])
            needed = (
                stories.SUMMARY_SAME_FEED_SCORE
                if by_id[a].feed_id == by_id[b].feed_id
                else stories.SUMMARY_CONTAIN_SCORE
            )
            if score >= needed:
                found[(a, b)] = score
    return found


def _corpus(seed):
    """Clusters of overlapping summaries plus noise, over a few days."""
    rng = random.Random(seed)
    common = [f"common{i}" for i in range(15)]
    posts, summaries = [], {}
    pid = 0
    for cluster in range(40):
        core = [f"event{cluster}x{i}" for i in range(rng.randint(4, 12))]
        start = T0 + timedelta(hours=rng.randint(0, 120))
        for _ in range(rng.randint(1, 5)):
            pid += 1
            words = rng.sample(core, rng.randint(1, len(core)))
            words += rng.sample(common, rng.randint(0, 8))
            words += [f"noise{rng.randint(0, 400)}" for _ in range(rng.randint(0, 10))]
            # Whole-hour offsets so some pairs sit exactly MAX_GAP apart
            date = start + timedelta(hours=rng.choice([0, 1, 5, 24, 47, 48, 49]))
            posts.append(StoryPost(pid, rng.randint(1, 4), date, f"Title {pid}"))
            summaries[pid] = " ".join(words)
    # Identical summaries give equal weights, exercising the tie-break
    pid += 1
    posts.append(StoryPost(pid, 9, T0, "Twin"))
    summaries[pid] = summaries[1]
    return {p.id: p for p in posts}, summaries


@pytest.mark.parametrize("seed", range(8))
def test_summary_pairs_match_brute_force(seed):
    by_id, summaries = _corpus(seed)

    scores = {}
    stories._add_summary_pairs(scores, by_id, summaries)

    expected = _brute_force(by_id, summaries)
    assert expected, "corpus should produce some pairs"
    assert scores == expected


def test_summary_pairs_keep_a_higher_existing_score():
    by_id = {
        1: StoryPost(1, 1, T0, "A"),
        2: StoryPost(2, 2, T0, "B"),
    }
    summaries = {1: "rocket launch orbit", 2: "rocket launch orbit"}
    scores = {(1, 2): 5.0}

    stories._add_summary_pairs(scores, by_id, summaries)

    assert scores == {(1, 2): 5.0}
