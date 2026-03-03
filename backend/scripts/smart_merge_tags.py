#!/usr/bin/env python3
"""
Smart tag merge: stem clustering + LLM refinement.

Phase 1: Group tags by shared word stems (no LLM, instant)
Phase 2: LLM confirms which clustered tags are true synonyms
Phase 3: LLM catch-all for ungrouped tags (abbreviations, semantic synonyms)

Usage:
    python scripts/smart_merge_tags.py                 # Dry run, Cerebras
    python scripts/smart_merge_tags.py --apply         # Execute merges
    python scripts/smart_merge_tags.py --local         # Use Ollama
    python scripts/smart_merge_tags.py --phase 1       # Stem clustering only
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from sqlalchemy import func, text

from app.database import SessionLocal
from app.models import PostTag
from app.services.cerebras._parsing import normalize_tag, parse_json_response
from app.services.suggestions import clear_all_suggestions
from app.services.user_profile import invalidate_user_profile

# Ollama settings (reuse from ollama module)
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"
OLLAMA_TIMEOUT = 600

# Tuning
MIN_SEGMENT_LEN = 3
DEFAULT_MAX_FAN_OUT = 30
BATCH_TAG_LIMIT = 50
CATCH_ALL_BATCH = 200
DELAY_CEREBRAS = 5
DELAY_LOCAL = 1

SYSTEM_PROMPT = (
    "You are a tag consolidation assistant for an RSS reader. "
    "Tags are lowercase, hyphenated English terms (e.g. 'machine-learning'). "
    "Your job is to identify groups of near-duplicate or synonym tags that "
    "should be merged into a single canonical tag."
)


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------
class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ---------------------------------------------------------------------------
# LLM callers
# ---------------------------------------------------------------------------
async def call_ollama_json(system_prompt: str, user_prompt: str) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 4096},
    }
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response = await client.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
    data = response.json()
    return parse_json_response(data["message"]["content"])


async def call_llm(system_prompt: str, user_prompt: str, use_local: bool = False) -> dict:
    if use_local:
        return await call_ollama_json(system_prompt, user_prompt)
    from app.services.cerebras._api import call_llm_json

    return await call_llm_json(system_prompt, user_prompt)


# ---------------------------------------------------------------------------
# Phase 1: Stem clustering
# ---------------------------------------------------------------------------
def build_stem_clusters(tag_counts: dict, max_fan_out: int) -> tuple:
    """Return (clusters, ungrouped) where clusters is list of list of tags.

    Uses direct stem grouping (NOT transitive closure) to avoid mega-clusters.
    Each stem that maps to 2..max_fan_out tags becomes a cluster.
    Overlapping clusters are merged only when they share >50% of their tags.
    """
    # Build inverted index
    index = defaultdict(set)
    for tag in tag_counts:
        segments = tag.split("-")
        for seg in segments:
            if len(seg) >= MIN_SEGMENT_LEN:
                index[seg].add(tag)

    # Filter high-fan-out and singleton segments
    filtered = {seg: tags for seg, tags in index.items() if len(tags) > max_fan_out}
    if filtered:
        log(f"Filtered {len(filtered)} high-fan-out segments: "
            + ", ".join(f"{s}({len(t)})" for s, t in sorted(filtered.items(), key=lambda x: -len(x[1]))[:10]))

    # Each qualifying stem is a cluster
    raw_clusters = []
    for seg, tags in index.items():
        if 2 <= len(tags) <= max_fan_out:
            raw_clusters.append(frozenset(tags))

    # Deduplicate identical clusters
    raw_clusters = list(set(raw_clusters))

    # Merge clusters that overlap >50%
    merged = True
    while merged:
        merged = False
        new_clusters = []
        used = set()
        for i in range(len(raw_clusters)):
            if i in used:
                continue
            current = set(raw_clusters[i])
            for j in range(i + 1, len(raw_clusters)):
                if j in used:
                    continue
                other = raw_clusters[j]
                overlap = len(current & other)
                smaller = min(len(current), len(other))
                if smaller > 0 and overlap / smaller > 0.5:
                    current |= other
                    used.add(j)
                    merged = True
            new_clusters.append(frozenset(current))
            used.add(i)
        raw_clusters = new_clusters

    # Convert to sorted lists, filter mega-clusters that formed during merge
    clusters = []
    clustered_tags = set()
    for c in raw_clusters:
        if len(c) <= max_fan_out * 2:  # Allow some growth from merging
            clusters.append(sorted(c))
            clustered_tags.update(c)

    # Ungrouped = tags not in any cluster
    ungrouped = sorted(t for t in tag_counts if t not in clustered_tags)

    return clusters, ungrouped


# ---------------------------------------------------------------------------
# Phase 2: LLM refinement of clusters
# ---------------------------------------------------------------------------
def build_cluster_prompt(clusters: list, tag_counts: dict) -> str:
    parts = []
    for i, cluster in enumerate(clusters, 1):
        lines = [f"- {tag} ({tag_counts[tag]} posts)" for tag in sorted(cluster, key=lambda t: -tag_counts[t])]
        parts.append(f"Group {i}:\n" + "\n".join(lines))

    return (
        "I have pre-grouped these tags by shared word stems. For each group, decide:\n"
        "- Which tags are TRUE synonyms/duplicates that should be merged?\n"
        "- Pick the most descriptive, commonly-used tag as canonical (prefer higher post counts)\n"
        "- Tags that are distinct concepts must NOT be merged "
        "(e.g. 'data-science' and 'data-privacy' are different)\n"
        "- A group may have NO true duplicates — skip it entirely\n\n"
        + "\n\n".join(parts)
        + '\n\nRespond ONLY in JSON:\n'
        '{"groups": [{"canonical": "best-tag", "merge": ["synonym1", "synonym2"]}]}\n'
        'If no true duplicates exist in any group, return {"groups": []}'
    )


def validate_groups(raw_groups: list, valid_tags: set) -> list:
    """Filter LLM response to only include valid tags."""
    groups = []
    for g in raw_groups:
        canonical = g.get("canonical", "")
        merge = [t for t in g.get("merge", []) if isinstance(t, str) and t in valid_tags and t != canonical]
        if canonical in valid_tags and merge:
            groups.append({"canonical": canonical, "merge": merge})
    return groups


async def refine_clusters_with_llm(clusters: list, tag_counts: dict, use_local: bool, delay: float) -> list:
    # Split into small (≤5 tags) and large (>5)
    small = [c for c in clusters if len(c) <= 5]
    large = [c for c in clusters if len(c) > 5]

    # Pack small clusters into batches
    batches = []
    current_batch, current_count = [], 0
    for cluster in small:
        if current_count + len(cluster) > BATCH_TAG_LIMIT and current_batch:
            batches.append(current_batch)
            current_batch, current_count = [], 0
        current_batch.append(cluster)
        current_count += len(cluster)
    if current_batch:
        batches.append(current_batch)

    # Each large cluster is its own batch
    for cluster in large:
        batches.append([cluster])

    log(f"Phase 2: {len(batches)} LLM batches ({len(small)} small clusters, {len(large)} large clusters)")

    all_groups = []
    errors = 0

    for i, batch_clusters in enumerate(batches, 1):
        all_tags_in_batch = set()
        for c in batch_clusters:
            all_tags_in_batch.update(c)

        prompt = build_cluster_prompt(batch_clusters, tag_counts)

        try:
            result = await call_llm(SYSTEM_PROMPT, prompt, use_local)
            groups = validate_groups(result.get("groups", []), all_tags_in_batch)
            all_groups.extend(groups)
            found = sum(len(g["merge"]) for g in groups)
            log(f"  Batch {i}/{len(batches)}: {len(batch_clusters)} clusters, "
                f"{len(all_tags_in_batch)} tags → {len(groups)} merge groups ({found} tags to merge)")
        except Exception as e:
            log(f"  Batch {i}/{len(batches)}: ERROR ({e})")
            errors += 1

        if i < len(batches):
            await asyncio.sleep(delay)

    if errors:
        log(f"  {errors} batches failed")

    return all_groups


# ---------------------------------------------------------------------------
# Phase 3: Catch-all for ungrouped tags
# ---------------------------------------------------------------------------
async def catch_all_ungrouped(ungrouped: list, tag_counts: dict, use_local: bool, delay: float, batch_size: int) -> list:
    if not ungrouped:
        return []

    batches = [ungrouped[i:i + batch_size] for i in range(0, len(ungrouped), batch_size)]
    log(f"Phase 3: {len(batches)} LLM batches ({len(ungrouped)} ungrouped tags)")

    all_groups = []
    errors = 0

    for i, batch in enumerate(batches, 1):
        tags_list = "\n".join(f"- {tag} ({tag_counts[tag]} posts)" for tag in batch)
        prompt = (
            f"Here are {len(batch)} tags that had no obvious word-stem overlap with other tags.\n"
            "Look especially for:\n"
            "- Acronyms and their expansions (e.g. 'ai' and 'artificial-intelligence')\n"
            "- Semantic synonyms with different wording (e.g. 'privacy' and 'data-privacy')\n"
            "- Spelling variations\n\n"
            f"{tags_list}\n\n"
            "Group any tags that are synonyms or near-duplicates.\n"
            "Pick the most descriptive, commonly-used tag as canonical (prefer higher post counts).\n"
            "Tags that are distinct concepts should NOT be grouped.\n\n"
            'Respond ONLY in JSON:\n'
            '{"groups": [{"canonical": "best-tag", "merge": ["synonym1", "synonym2"]}]}\n'
            'If no duplicates are found, return {"groups": []}'
        )

        valid_tags = set(batch)
        try:
            result = await call_llm(SYSTEM_PROMPT, prompt, use_local)
            groups = validate_groups(result.get("groups", []), valid_tags)
            all_groups.extend(groups)
            found = sum(len(g["merge"]) for g in groups)
            log(f"  Batch {i}/{len(batches)}: {len(batch)} tags → {len(groups)} merge groups ({found} tags to merge)")
        except Exception as e:
            log(f"  Batch {i}/{len(batches)}: ERROR ({e})")
            errors += 1

        if i < len(batches):
            await asyncio.sleep(delay)

    if errors:
        log(f"  {errors} batches failed")

    return all_groups


# ---------------------------------------------------------------------------
# Merge execution
# ---------------------------------------------------------------------------
def apply_merges_to_db(db, merge_groups: list) -> tuple:
    tags_removed = 0
    posts_affected = 0

    for group in merge_groups:
        canonical = normalize_tag(group["canonical"])
        if not canonical:
            continue
        for source in group["merge"]:
            source = normalize_tag(source)
            if not source or source == canonical:
                continue

            # post_tags: delete conflicts, then rename
            db.execute(
                text(
                    "DELETE FROM post_tags WHERE tag = :source "
                    "AND post_id IN ("
                    "  SELECT post_id FROM post_tags WHERE tag = :canonical"
                    ")"
                ),
                {"source": source, "canonical": canonical},
            )
            result = db.execute(
                text("UPDATE post_tags SET tag = :canonical WHERE tag = :source"),
                {"source": source, "canonical": canonical},
            )
            posts_affected += result.rowcount

            # topic_tags
            db.execute(
                text(
                    "DELETE FROM topic_tags WHERE tag = :source "
                    "AND topic_id IN ("
                    "  SELECT topic_id FROM topic_tags WHERE tag = :canonical"
                    ")"
                ),
                {"source": source, "canonical": canonical},
            )
            db.execute(
                text("UPDATE topic_tags SET tag = :canonical WHERE tag = :source"),
                {"source": source, "canonical": canonical},
            )

            # ignored_tags
            db.execute(
                text("DELETE FROM ignored_tags WHERE tag = :source"),
                {"source": source},
            )

            tags_removed += 1

    db.commit()
    if tags_removed > 0:
        clear_all_suggestions(db)
        invalidate_user_profile(db)

    return tags_removed, posts_affected


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Smart tag merge: stem clustering + LLM refinement.")
    parser.add_argument("--apply", action="store_true", help="Execute merges (default: dry run)")
    parser.add_argument("--local", action="store_true", help="Use Ollama instead of Cerebras")
    parser.add_argument("--phase", type=int, default=3, choices=[1, 2, 3], help="Stop after phase N")
    parser.add_argument("--max-fan-out", type=int, default=DEFAULT_MAX_FAN_OUT, help="Max tags per stem segment")
    parser.add_argument("--catch-all-batch", type=int, default=CATCH_ALL_BATCH, help="Batch size for phase 3")
    return parser.parse_args()


async def main():
    args = parse_args()
    delay = DELAY_LOCAL if args.local else DELAY_CEREBRAS
    mode = "local/Ollama" if args.local else "Cerebras"

    db = SessionLocal()

    # Load all tags
    rows = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .group_by(PostTag.tag)
        .all()
    )
    tag_counts = {row.tag: row.count for row in rows}
    log(f"Loaded {len(tag_counts)} unique tags (mode: {mode})\n")

    # --- Phase 1 ---
    log("=== Phase 1: Stem Clustering ===")
    clusters, ungrouped = build_stem_clusters(tag_counts, args.max_fan_out)
    clustered_count = sum(len(c) for c in clusters)
    log(f"Found {len(clusters)} clusters ({clustered_count} tags), {len(ungrouped)} ungrouped\n")

    if args.phase == 1:
        # Output clusters for inspection
        for i, cluster in enumerate(sorted(clusters, key=len, reverse=True), 1):
            tags_str = ", ".join(f"{t}({tag_counts[t]})" for t in sorted(cluster, key=lambda t: -tag_counts[t]))
            log(f"  Cluster {i} [{len(cluster)} tags]: {tags_str}")
        db.close()
        return

    # --- Phase 2 ---
    log("=== Phase 2: LLM Refinement ===")
    all_groups = await refine_clusters_with_llm(clusters, tag_counts, args.local, delay)
    log(f"Phase 2 complete: {len(all_groups)} merge groups\n")

    # --- Phase 3 ---
    if args.phase >= 3:
        log("=== Phase 3: Catch-All ===")
        phase3_groups = await catch_all_ungrouped(ungrouped, tag_counts, args.local, delay, args.catch_all_batch)
        log(f"Phase 3 complete: {len(phase3_groups)} merge groups\n")
        all_groups.extend(phase3_groups)

    # --- Summary ---
    total_to_merge = sum(len(g["merge"]) for g in all_groups)
    log(f"=== Summary ===")
    log(f"Total merge groups: {len(all_groups)} ({total_to_merge} tags to remove)")

    if all_groups:
        log("\nMerge plan:")
        for g in all_groups:
            log(f"  {g['merge']} → {g['canonical']}")

    # Output JSON
    print("\n" + json.dumps(all_groups, indent=2))

    # --- Apply ---
    if args.apply and all_groups:
        log(f"\nApplying {len(all_groups)} merge groups...")
        tags_removed, posts_affected = apply_merges_to_db(db, all_groups)
        log(f"Applied: {tags_removed} tags merged, {posts_affected} posts affected")
    elif all_groups and not args.apply:
        log("\nDry run — use --apply to execute merges")

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
