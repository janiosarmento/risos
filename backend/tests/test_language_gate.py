"""Tests for the post-summary language gate.

The detection logic is pure and deterministic (langdetect with a fixed seed);
the enforcement orchestration is exercised with a fake translate callback so no
network/LLM is needed.
"""

import pytest

from app.services.ai._language_gate import (
    _resolve_lang_code,
    _strip_fences,
    detect_foreign_sentences,
    enforce_language,
)
from app.services.ai._parsing import split_into_sentences

CLEAN_PT = (
    "A Apple anunciou o novo chip A20 com melhor desempenho.\n\n"
    "• O site da empresa saiu do ar apos o lancamento\n"
    "• O novo software chega em setembro de 2026"
)

MIXED = (
    "Suposta imagem do chip A20 aparece em vazamento.\n\n"
    "The A20 chip was announced yesterday during the keynote event.\n\n"
    "• chip"
)


# --- language code resolution ------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    [
        ("Brazilian Portuguese", "pt"),
        ("Portuguese", "pt"),
        ("English", "en"),
        ("Spanish", "es"),
        ("pt", "pt"),
        ("zh-cn", "zh-cn"),
    ],
)
def test_resolve_known_languages(name, code):
    assert _resolve_lang_code(name) == code


def test_resolve_unknown_language_returns_none():
    assert _resolve_lang_code("Klingon") is None
    assert _resolve_lang_code("") is None


# --- sentence splitting ------------------------------------------------------


def test_split_keeps_abbreviations_and_bullets_separate():
    text = "Veja o Dr. Silva. Ele falou.\n• item um\n• item dois"
    sentences = split_into_sentences(text)
    assert "Veja o Dr. Silva." in sentences
    assert "Ele falou." in sentences
    assert "• item um" in sentences
    assert "• item dois" in sentences


# --- detection ---------------------------------------------------------------


def test_clean_portuguese_with_loanwords_has_no_foreign():
    # "chip", "site", "software" are legitimate loanwords; must not be flagged.
    assert detect_foreign_sentences(CLEAN_PT, "pt") == []


def test_mixed_text_flags_only_the_foreign_sentence():
    foreign = detect_foreign_sentences(MIXED, "pt")
    assert len(foreign) == 1
    assert foreign[0].startswith("The A20")


def test_short_fragment_is_ignored():
    # A 4-char fragment like "chip" is below the min length and unreliable.
    assert detect_foreign_sentences("chip", "pt") == []


# --- fence stripping ---------------------------------------------------------


def test_strip_fences():
    assert _strip_fences("```\nhello\n```") == "hello"
    assert _strip_fences("```text\nhello\n```") == "hello"
    assert _strip_fences("plain") == "plain"


# --- enforcement orchestration ----------------------------------------------


@pytest.mark.asyncio
async def test_clean_text_skips_llm_call():
    async def translate(_system, _user):
        raise AssertionError("translate must not be called on clean text")

    assert await enforce_language(CLEAN_PT, "Brazilian Portuguese", translate) == CLEAN_PT


@pytest.mark.asyncio
async def test_mixed_text_accepts_improved_cleanup():
    cleaned = (
        "Suposta imagem do chip A20 aparece em vazamento.\n\n"
        "O chip A20 foi anunciado ontem durante o evento principal."
    )

    async def translate(_system, _user):
        return cleaned

    out = await enforce_language(MIXED, "Brazilian Portuguese", translate)
    assert out == cleaned
    assert detect_foreign_sentences(out, "pt") == []


@pytest.mark.asyncio
async def test_cleanup_without_improvement_keeps_original():
    async def translate(_system, _user):
        return MIXED  # still has the English sentence

    assert await enforce_language(MIXED, "Brazilian Portuguese", translate) == MIXED


@pytest.mark.asyncio
async def test_too_short_cleanup_keeps_original():
    async def translate(_system, _user):
        return "ok"

    assert await enforce_language(MIXED, "Brazilian Portuguese", translate) == MIXED


@pytest.mark.asyncio
async def test_translate_exception_keeps_original():
    async def translate(_system, _user):
        raise RuntimeError("llm down")

    assert await enforce_language(MIXED, "Brazilian Portuguese", translate) == MIXED
