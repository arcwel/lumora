"""Pinned LLM-as-judge prompts.

Judge prompts are versioned and content-hashed so every ``Score`` row can be
traced back to the exact rubric that produced it. Never edit an existing
version in place — add a new version and bump ``CURRENT_JUDGE_PROMPT_VERSION``.
"""

from __future__ import annotations

import hashlib

CURRENT_JUDGE_PROMPT_VERSION = "v1"

#: Mapping of version -> system prompt text. Append-only.
JUDGE_PROMPTS: dict[str, str] = {
    "v1": (
        "You are an impartial evaluator measuring how a brand appears in an AI "
        "assistant's answer. Given the brand name (and its aliases) and the raw "
        "answer text, return a strict JSON object with these keys:\n"
        '  - "brand_mentioned" (boolean): whether the brand or any alias appears.\n'
        '  - "mention_position" (integer or null): 1-based rank of the brand among '
        "distinct named entities/products in the answer; null if not mentioned.\n"
        '  - "sentiment" (one of "pos", "neu", "neg" or null): sentiment toward the '
        "brand in context; null if not mentioned.\n"
        '  - "cited_sources" (array of strings): URLs or source names the answer '
        "attributes to the brand or its mention.\n"
        "Judge only what is present in the answer. Do not use outside knowledge. "
        "Respond with JSON only, no prose."
    ),
}


def get_judge_prompt(version: str = CURRENT_JUDGE_PROMPT_VERSION) -> str:
    """Return the pinned judge prompt text for ``version``."""

    try:
        return JUDGE_PROMPTS[version]
    except KeyError as exc:
        raise ValueError(f"Unknown judge prompt version: {version!r}") from exc


def judge_prompt_hash(version: str = CURRENT_JUDGE_PROMPT_VERSION) -> str:
    """Return a stable SHA-256 hash of the pinned judge prompt text."""

    return hashlib.sha256(get_judge_prompt(version).encode("utf-8")).hexdigest()
