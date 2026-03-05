#!/usr/bin/env python3
"""
Batch-translate all non-English tags in the database to English.
Uses Cerebras llama3.1-8b for translation, same as the live pipeline.
Rotates through ALL configured API keys round-robin to avoid rate limits.
Updates post_tags rows in-place and also updates user_profile tags.
"""

import asyncio
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import PostTag, AppSettings
from app.services.cerebras._constants import (
    CEREBRAS_API_URL,
    TAG_TRANSLATION_MODEL,
    TAG_TRANSLATION_TEMPERATURE,
    TAG_TRANSLATION_MAX_TOKENS,
    TAG_TRANSLATION_TIMEOUT,
)
from app.services.cerebras._parsing import normalize_tag
from app.services.cerebras._infrastructure import api_key_rotator

import httpx
import json

# Portuguese patterns to detect non-English tags (even without accents)
PT_PATTERNS = [
    re.compile(r"-(de|do|da|dos|das|em|no|na|nos|nas|para|por|com|sem)-"),
    re.compile(r"-(de|do|da|dos|das|em|no|na|nos|nas|para|por|com|sem)$"),
    re.compile(r"^(de|do|da|dos|das|em|no|na|nos|nas|para|por|com|sem)-"),
]


def is_likely_non_english(tag: str) -> bool:
    """Check if a tag is likely non-English."""
    if not all(ord(c) < 128 for c in tag):
        return True
    for pat in PT_PATTERNS:
        if pat.search(tag):
            return True
    return False


def get_all_keys() -> list:
    """Get all API keys from configuration."""
    return api_key_rotator._get_keys()


async def translate_batch(tags: list, api_key: str, key_label: str) -> dict:
    """Translate a batch of tags. Returns {old_tag: new_tag} mapping."""
    tags_str = ", ".join(tags)
    messages = [
        {
            "role": "system",
            "content": "You translate tags to English. Reply with ONLY the comma-separated translated tags, nothing else. Keep the EXACT same order and count as input.",
        },
        {
            "role": "user",
            "content": f"Translate these tags to English (keep brand names, proper nouns, and already-English tags exactly as-is; use lowercase hyphens): {tags_str}",
        },
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": TAG_TRANSLATION_MODEL,
        "messages": messages,
        "temperature": TAG_TRANSLATION_TEMPERATURE,
        "max_tokens": TAG_TRANSLATION_MAX_TOKENS,
    }

    async with httpx.AsyncClient(timeout=TAG_TRANSLATION_TIMEOUT) as client:
        response = await client.post(
            CEREBRAS_API_URL, headers=headers, json=payload
        )

        if response.status_code == 429:
            # This key is rate-limited; caller will switch to next key
            return None  # sentinel: rate limited

        if response.status_code != 200:
            print(f"  ERROR [{key_label}]: HTTP {response.status_code}")
            return {}

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        translated = [normalize_tag(t) for t in content.split(",")]
        translated = [t for t in translated if t]

        if len(translated) != len(tags):
            print(
                f"  WARNING [{key_label}]: sent {len(tags)} tags, got {len(translated)} back"
            )
            if len(translated) < len(tags) // 2:
                return {}

        mapping = {}
        for i, old_tag in enumerate(tags):
            if i < len(translated) and translated[i] != old_tag:
                mapping[old_tag] = translated[i]
        return mapping


async def main():
    db = SessionLocal()

    # Get all distinct tags
    all_tags = sorted(
        set(t[0] for t in db.query(PostTag.tag).distinct().all())
    )
    non_english = [t for t in all_tags if is_likely_non_english(t)]
    print(f"Total distinct tags: {len(all_tags)}")
    print(f"Non-English tags to translate: {len(non_english)}")

    if not non_english:
        print("Nothing to do!")
        db.close()
        return

    # Get ALL API keys for round-robin
    keys = get_all_keys()
    if not keys:
        print("ERROR: No API keys configured")
        db.close()
        return
    print(f"API keys available: {len(keys)}")

    # Process in batches of 30 tags, rotating keys
    BATCH_SIZE = 30
    total_translated = 0
    total_rows_updated = 0
    full_mapping = {}  # old_tag -> new_tag
    key_index = 0

    i = 0
    while i < len(non_english):
        batch = non_english[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(non_english) + BATCH_SIZE - 1) // BATCH_SIZE

        api_key = keys[key_index % len(keys)]
        key_label = f"key {key_index % len(keys) + 1}/{len(keys)}"
        print(
            f"\nBatch {batch_num}/{total_batches} ({len(batch)} tags) [{key_label}]..."
        )

        try:
            mapping = await translate_batch(batch, api_key, key_label)
        except Exception as e:
            print(f"  ERROR [{key_label}]: {e}")
            key_index += 1
            await asyncio.sleep(2)
            continue

        if mapping is None:
            # Rate limited on this key — rotate and retry same batch
            print(f"  Rate limited on {key_label}, rotating...")
            key_index += 1
            # If we've tried all keys, wait before retrying
            if key_index % len(keys) == 0:
                print("  All keys rate limited, waiting 30s...")
                await asyncio.sleep(30)
            continue

        if mapping:
            full_mapping.update(mapping)
            # Apply translations to database — one tag at a time with flush
            for old_tag, new_tag in mapping.items():
                rows = db.query(PostTag).filter(PostTag.tag == old_tag).all()
                for row in rows:
                    # Check for duplicate (post already has new_tag)
                    existing = (
                        db.query(PostTag)
                        .filter(
                            PostTag.post_id == row.post_id,
                            PostTag.tag == new_tag,
                        )
                        .first()
                    )
                    if existing:
                        db.delete(row)
                    else:
                        row.tag = new_tag
                    total_rows_updated += 1
                # Flush after each distinct tag to avoid batch UNIQUE conflicts
                db.flush()

            db.commit()
            total_translated += len(mapping)
            print(
                f"  Translated {len(mapping)} tags, {total_rows_updated} rows updated so far"
            )
            for old, new in sorted(mapping.items()):
                print(f"    {old} -> {new}")

        # Advance to next batch and rotate key
        i += BATCH_SIZE
        key_index += 1
        # Small delay to be polite
        await asyncio.sleep(0.3)

    # Also update user profile tags
    print("\nUpdating user profile tags...")
    profile_row = (
        db.query(AppSettings).filter(AppSettings.key == "user_profile").first()
    )
    if profile_row:
        profile = json.loads(profile_row.value)
        if profile.get("tags"):
            old_profile_tags = profile["tags"]
            new_profile_tags = []
            for t in old_profile_tags:
                normalized = normalize_tag(t)
                new_profile_tags.append(
                    full_mapping.get(normalized, normalized)
                )
            # Deduplicate
            new_profile_tags = list(dict.fromkeys(new_profile_tags))
            profile["tags"] = new_profile_tags
            profile_row.value = json.dumps(profile)
            db.commit()
            changed = [
                f"{o} -> {full_mapping[normalize_tag(o)]}"
                for o in old_profile_tags
                if normalize_tag(o) in full_mapping
            ]
            print(f"  Profile tags updated: {len(changed)} translated")
            for c in changed:
                print(f"    {c}")

    db.close()
    print(
        f"\nDone! Translated {total_translated} distinct tags, {total_rows_updated} total rows."
    )


if __name__ == "__main__":
    asyncio.run(main())
