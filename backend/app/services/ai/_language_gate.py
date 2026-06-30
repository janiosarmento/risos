"""Post-summary language gate.

Local models often ignore the "write everything in {language}" instruction and
leave stray sentences in another language (usually English). This module detects
that cheaply, per sentence, and only when a confident mismatch is found does it
run a single LLM cleanup pass that translates the offending spans while keeping
everything else identical.

Detection is deterministic and dependency-light (langdetect, pure Python). The
gate never raises: on any problem it returns the original text unchanged, so it
can only improve a summary, never break one.
"""

import logging
import re
from typing import Awaitable, Callable, List, Optional

from app.services.ai._constants import (
    LANGUAGE_GATE_CONFIDENCE,
    LANGUAGE_GATE_ENABLED,
    LANGUAGE_GATE_MIN_LENGTH_RATIO,
    LANGUAGE_GATE_MIN_SENTENCE_CHARS,
)
from app.services.ai._parsing import split_into_sentences

logger = logging.getLogger(__name__)

# A callable that performs the actual LLM call: (system_prompt, user_prompt) ->
# plain-text response. Injected by each summary path so this module stays
# independent of the transport (OpenAI-compatible, Ollama, etc.).
TranslateFn = Callable[[str, str], Awaitable[str]]

try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException

    # Make detection reproducible (langdetect is randomized by default).
    DetectorFactory.seed = 0
    _LANGDETECT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when dep is missing
    _LANGDETECT_AVAILABLE = False
    LangDetectException = Exception  # type: ignore


# Map the human-readable language name stored in preferences (e.g. "Brazilian
# Portuguese") to the ISO 639-1 code langdetect emits. Substring match, so
# variants ("European Portuguese", "português do Brasil") resolve correctly.
_LANG_NAME_TO_CODE = [
    ("portug", "pt"),
    ("portuguê", "pt"),
    ("english", "en"),
    ("ingl", "en"),
    ("spanish", "es"),
    ("espa", "es"),
    ("french", "fr"),
    ("fran", "fr"),
    ("german", "de"),
    ("deutsch", "de"),
    ("alem", "de"),
    ("italian", "it"),
    ("ital", "it"),
    ("dutch", "nl"),
    ("holand", "nl"),
    ("russian", "ru"),
    ("russ", "ru"),
    ("japanese", "ja"),
    ("japon", "ja"),
    ("korean", "ko"),
    ("corean", "ko"),
    ("chinese", "zh-cn"),
    ("chin", "zh-cn"),
]

_FENCE_RE = re.compile(r"^```(?:\w+)?\s*([\s\S]*?)\s*```$")


def _resolve_lang_code(language_name: str) -> Optional[str]:
    """Resolve a human language name to a langdetect ISO code, or None."""
    if not language_name:
        return None
    name = language_name.strip().lower()
    for needle, code in _LANG_NAME_TO_CODE:
        if needle in name:
            return code
    # Already a bare ISO code (e.g. "pt", "en", "zh-cn").
    if re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", name):
        return name
    return None


def detect_foreign_sentences(text: str, target_code: str) -> List[str]:
    """Return the sentences confidently written in a language other than the
    target. Short sentences and undetectable spans are ignored."""
    if not _LANGDETECT_AVAILABLE or not text or not target_code:
        return []

    foreign: List[str] = []
    for sentence in split_into_sentences(text):
        if len(sentence) < LANGUAGE_GATE_MIN_SENTENCE_CHARS:
            continue
        try:
            langs = detect_langs(sentence)
        except LangDetectException:
            continue
        if not langs:
            continue
        top = langs[0]
        if top.lang != target_code and top.prob >= LANGUAGE_GATE_CONFIDENCE:
            foreign.append(sentence)
    return foreign


def _build_cleanup_messages(text: str, language_name: str) -> tuple:
    """Build (system_prompt, user_prompt) for the cleanup pass."""
    system_prompt = (
        "You are a meticulous translator and copy editor. You fix text that "
        "accidentally mixes languages so it reads as if written by a native "
        "speaker, without changing its meaning."
    )
    user_prompt = (
        f"The text below is a news summary that must be written ENTIRELY in "
        f"{language_name}. Some sentences or phrases are mistakenly in another "
        f"language (usually English). Rewrite it so EVERYTHING is in "
        f"{language_name}, following these rules:\n"
        f"- Preserve the meaning, facts, numbers, dates and names EXACTLY. "
        f"Do not add or remove information.\n"
        f"- Keep the exact same structure: same paragraphs, same bullet points "
        f"(•), same line breaks.\n"
        f"- Keep proper nouns, brand names, product names and established "
        f'technical loanwords as-is (e.g. "chip", "site", "software", '
        f'"iPhone", "GitHub"). Do NOT invent words or awkwardly conjugate '
        f"foreign verbs.\n"
        f"- Only translate the parts that are in the wrong language; leave "
        f"already-correct {language_name} text untouched.\n"
        f"- Return ONLY the corrected text: no preamble, no explanation, no "
        f"code fences.\n\n"
        f"Text:\n{text}"
    )
    return system_prompt, user_prompt


def _strip_fences(text: str) -> str:
    """Remove a wrapping markdown code fence if the model added one."""
    match = _FENCE_RE.match(text.strip())
    return match.group(1) if match else text


async def enforce_language(
    text: str, language_name: str, translate_fn: TranslateFn
) -> str:
    """Ensure ``text`` is entirely in ``language_name``.

    Detects mixed-language content per sentence; if any confident foreign
    sentence is found, runs a single cleanup pass via ``translate_fn`` and
    returns the result only when it is a clear improvement. Returns the original
    text unchanged on any problem — this function never raises.
    """
    if not LANGUAGE_GATE_ENABLED or not text or not text.strip():
        return text

    try:
        target_code = _resolve_lang_code(language_name)
        if not target_code:
            return text

        foreign = detect_foreign_sentences(text, target_code)
        if not foreign:
            return text

        logger.info(
            "Language gate: %d foreign-language sentence(s) detected "
            "(target=%s); running cleanup",
            len(foreign),
            target_code,
        )

        system_prompt, user_prompt = _build_cleanup_messages(text, language_name)
        cleaned = await translate_fn(system_prompt, user_prompt)
        cleaned = _strip_fences((cleaned or "")).strip()

        if not cleaned:
            logger.warning("Language gate: cleanup returned empty; keeping original")
            return text

        if len(cleaned) < LANGUAGE_GATE_MIN_LENGTH_RATIO * len(text):
            logger.warning(
                "Language gate: cleanup too short (%d < %.0f%% of %d); "
                "keeping original",
                len(cleaned),
                LANGUAGE_GATE_MIN_LENGTH_RATIO * 100,
                len(text),
            )
            return text

        remaining = detect_foreign_sentences(cleaned, target_code)
        if len(remaining) >= len(foreign):
            logger.warning(
                "Language gate: cleanup did not reduce foreign content "
                "(%d -> %d); keeping original",
                len(foreign),
                len(remaining),
            )
            return text

        logger.info(
            "Language gate: cleanup reduced foreign sentences %d -> %d",
            len(foreign),
            len(remaining),
        )
        return cleaned

    except Exception as e:
        logger.warning("Language gate failed, keeping original: %s", e)
        return text
