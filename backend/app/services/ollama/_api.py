"""Ollama API client for local LLM summary generation."""

import logging

import httpx

from app.config import USER_AGENT
from app.services.ai._constants import MAX_CONTENT_LENGTH, MAX_TAGS
from app.services.ai._parsing import (
    is_garbage_content,
    normalize_tags,
    parse_json_response,
)
from app.services.ai._prompts import get_system_prompt, get_user_prompt
from app.services.ai._types import GarbageContentError, SummaryResult

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"
OLLAMA_TIMEOUT = 600  # 10 minutes — CPU inference is slow


async def generate_summary_local(
    content: str, title: str = "", db=None
) -> SummaryResult:
    """Generate summary using local Ollama model. Same interface as Cerebras."""
    if is_garbage_content(content):
        raise GarbageContentError("Garbage content detected")

    import time
    start_time = time.time()

    content = content[:MAX_CONTENT_LENGTH]

    system_prompt = get_system_prompt(db)
    user_prompt = get_user_prompt(content, title, db=db)

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 2048,
        },
    }

    async with httpx.AsyncClient(
        timeout=OLLAMA_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.post(OLLAMA_URL, json=payload)
        response.raise_for_status()

    data = response.json()
    raw_text = data["message"]["content"]

    eval_count = data.get("eval_count", 0)
    eval_duration = data.get("eval_duration", 1)
    tok_s = eval_count / (eval_duration / 1e9) if eval_duration else 0
    logger.info(
        "Ollama: %d tokens in %.1fs (%.1f tok/s)",
        eval_count,
        eval_duration / 1e9,
        tok_s,
    )

    # Parse JSON response
    try:
        result = parse_json_response(raw_text)
    except ValueError as e:
        logger.warning("Ollama JSON parse failed: %s", e)
        raise ValueError(f"Failed to parse Ollama response: {e}") from e

    summary_pt = result.get("summary_pt", "").strip()
    one_line = result.get("one_line_summary", "").strip()
    translated_title = result.get("translated_title")
    tags = normalize_tags(result.get("tags", []), MAX_TAGS)

    if not summary_pt and not one_line:
        raise GarbageContentError(
            "Model returned empty result (unusable content)"
        )

    duration = time.time() - start_time

    return SummaryResult(
        summary_pt=summary_pt,
        one_line_summary=one_line,
        translated_title=translated_title,
        tags=tags,
        model=f"ollama/{OLLAMA_MODEL}",
        duration=duration,
    )
