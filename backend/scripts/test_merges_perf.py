#!/usr/bin/env python3
"""
Performance diagnostic script for tag merge suggestions batch.
Runs the exact pre-filtering algorithm on batch 2 (offset 100, batch_size 100)
and prints execution metrics and candidate groups.

Usage:
    python scripts/test_merges_perf.py
"""

import sys
import os
import time
from collections import defaultdict

# Resolve backend imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func
from app.database import SessionLocal
from app.models import PostTag
from app.routes.tags import _edit_dist, _get_digits, _get_initials

def main():
    print("Connecting to database...")
    db = SessionLocal()
    try:
        t0 = time.monotonic()
        total_tags = db.query(func.count(func.distinct(PostTag.tag))).scalar() or 0
        
        # Batch 2 configuration (offset 100, batch_size 100)
        offset = 100
        batch_size = 100
        
        rows = (
            db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
            .group_by(PostTag.tag)
            .order_by(PostTag.tag)
            .offset(offset)
            .limit(batch_size)
            .all()
        )
        
        all_rows = (
            db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
            .group_by(PostTag.tag)
            .all()
        )
        
        print(f"\n--- Database Metrics ---")
        print(f"Total distinct tags: {total_tags}")
        print(f"Active batch tags in alphabetical window (offset {offset}, size {batch_size}): {len(rows)}")
        print(f"Total unique tags in DB: {len(all_rows)}")
        
        t_pre = time.monotonic()
        
        # 1. Pre-compute metadata
        tag_metadata = {}
        for r in all_rows:
            t = r.tag
            t_clean = t.strip().lower()
            tag_metadata[t] = {
                "count": r.count,
                "clean": t_clean,
                "digits": _get_digits(t_clean),
                "initials": _get_initials(t_clean),
                "parts": [p for p in t_clean.split("-") if p],
            }
            
        # 2. Build segments index
        segment_to_tags = defaultdict(set)
        for tag, meta in tag_metadata.items():
            for p in meta["parts"]:
                if len(p) >= 3:
                    segment_to_tags[p].add(tag)
                    
        # 3. Identify generic categories (fan-out > 5)
        generic_segments = {seg for seg, tags in segment_to_tags.items() if len(tags) > 5}
        print(f"Generic segments (>5 tags): {len(generic_segments)} identified (out of {len(segment_to_tags)} total)")
        
        # 4. Filter candidate groups
        groups_to_eval = []
        seen_groups = set()
        
        for row in rows:
            t1 = row.tag
            if t1 not in tag_metadata:
                continue
            meta1 = tag_metadata[t1]
            t1_clean = meta1["clean"]
            t1_parts = meta1["parts"]
            t1_initials = meta1["initials"]
            t1_digits = meta1["digits"]
            
            candidates = []
            for t2, meta2 in tag_metadata.items():
                if t2 == t1:
                    continue
                
                # Heuristic 1: digit mismatch early reject
                if t1_digits != meta2["digits"]:
                    continue
                    
                t2_clean = meta2["clean"]
                
                # Heuristic 2: exact hyphen mismatch
                if t1_clean.replace("-", "") == t2_clean.replace("-", ""):
                    candidates.append(t2)
                    continue
                    
                # Heuristic 3: plural/singular
                if t1_clean + "s" == t2_clean or t2_clean + "s" == t1_clean:
                    candidates.append(t2)
                    continue
                    
                # Heuristic 4: initials/acronym match
                t2_initials = meta2["initials"]
                if (t1_initials and t1_initials == t2_clean) or (t2_initials and t2_initials == t1_clean):
                    candidates.append(t2)
                    continue
                    
                # Heuristic 5: edit distance spelling check
                if len(t1_clean) >= 4 and len(t2_clean) >= 4:
                    len_diff = abs(len(t1_clean) - len(t2_clean))
                    if len_diff <= 1 and _edit_dist(t1_clean, t2_clean) <= 1:
                        candidates.append(t2)
                        continue
                    if len(t1_clean) >= 6 and len(t2_clean) >= 6 and len_diff <= 2 and _edit_dist(t1_clean, t2_clean) <= 2:
                        candidates.append(t2)
                        continue
                        
                # Heuristic 6: specific segment matching
                t2_parts = meta2["parts"]
                shared_parts = set(t1_parts).intersection(set(t2_parts))
                significant_shared = False
                for p in shared_parts:
                    if len(p) >= 3 and p not in generic_segments:
                        significant_shared = True
                        break
                if significant_shared:
                    candidates.append(t2)
                    continue
                    
            if candidates:
                group = sorted([t1] + candidates)
                group_key = tuple(group)
                if group_key not in seen_groups:
                    seen_groups.add(group_key)
                    groups_to_eval.append(group)
                    
        elapsed = time.monotonic() - t0
        print(f"\n--- Performance Metrics ---")
        print(f"Pre-filtering algorithm execution time: {elapsed * 1000:.2f} ms")
        print(f"Generated candidate groups for LLM to evaluate: {len(groups_to_eval)}")
        
        print(f"\n--- Candidate Groups Details ---")
        if not groups_to_eval:
            print("No groups found. Short-circuit occurred (runs instantly, no LLM call required).")
        else:
            for i, g in enumerate(groups_to_eval, 1):
                members = ", ".join(f"{tag}({tag_metadata[tag]['count']})" for tag in g)
                print(f"Group {i}: [{members}]")
                
    finally:
        db.close()

if __name__ == "__main__":
    main()
