"""Prompt construction for the Cerebras client."""

from datetime import datetime

from app.config import load_prompts, settings


def get_system_prompt(db=None) -> str:
    """Returns the system prompt from DB settings or prompts.yaml fallback."""
    if db:
        from app.routes.preferences import get_effective_system_prompt
        return get_effective_system_prompt(db)
    prompts = load_prompts()
    return prompts.get(
        "system_prompt",
        "You are a helpful assistant that summarizes articles.",
    )


def get_user_prompt(content: str, title: str = "", language: str = None, db=None) -> str:
    """
    Returns the user prompt with content, title, language, and date interpolated.
    Reads template from DB settings or prompts.yaml fallback.
    If language is not provided, uses settings.summary_language as fallback.
    """
    if db:
        from app.routes.preferences import get_effective_user_prompt, get_effective_tags_per_post
        template = get_effective_user_prompt(db)
        tags_count = get_effective_tags_per_post(db)
    else:
        prompts = load_prompts()
        template = prompts.get(
            "user_prompt", "Summarize this article in {language}:\n\n{content}"
        )
        tags_count = 7
    prompt = template.format(
        language=language or settings.summary_language,
        content=content,
        title=title or "Untitled",
        date=datetime.now().strftime("%Y-%m-%d"),
        tags_count=tags_count,
    )

    # Always append tag language enforcement (models ignore it when buried in system prompt)
    prompt += (
        "\n\nIMPORTANT: All tags MUST be in English, using lowercase hyphens "
        "(e.g. \"open-source\", \"artificial-intelligence\"). "
        "NEVER use tags in other languages."
    )

    return prompt
