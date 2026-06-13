"""LLM-as-judge scoring pipeline.

Takes a raw answer plus brand context and produces a structured ``ScoreResult``
that maps directly onto the ``Score`` model. The vendor judge call is stubbed
for the scaffold; ``parse_judge_output`` is real so the contract is testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.config import settings
from app.judge.rubric import (
    CURRENT_JUDGE_PROMPT_VERSION,
    get_judge_prompt,
    judge_prompt_hash,
)
from app.models.score import Sentiment

_VALID_SENTIMENTS = {s.value for s in Sentiment}


@dataclass(slots=True)
class ScoreResult:
    """Structured judgement, ready to persist as a ``Score`` row."""

    brand_mentioned: bool
    mention_position: int | None
    sentiment: Sentiment | None
    cited_sources: list[str] = field(default_factory=list)
    judge_model: str = ""
    judge_prompt_hash: str = ""


def build_judge_user_message(brand_name: str, aliases: list[str], answer_text: str) -> str:
    """Assemble the user-message payload handed to the judge model."""

    alias_str = ", ".join(aliases) if aliases else "(none)"
    return (
        f"Brand: {brand_name}\n"
        f"Aliases: {alias_str}\n"
        "--- Answer to evaluate ---\n"
        f"{answer_text}"
    )


def parse_judge_output(raw: str, judge_model: str, prompt_version: str) -> ScoreResult:
    """Parse strict-JSON judge output into a ``ScoreResult``.

    Tolerates code-fenced JSON. Raises ``ValueError`` on unparseable output.
    """

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Strip a leading ```json / ``` fence and trailing fence.
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Judge output was not valid JSON: {exc}") from exc

    sentiment_raw = data.get("sentiment")
    sentiment = (
        Sentiment(sentiment_raw)
        if sentiment_raw in _VALID_SENTIMENTS
        else None
    )

    return ScoreResult(
        brand_mentioned=bool(data.get("brand_mentioned", False)),
        mention_position=data.get("mention_position"),
        sentiment=sentiment,
        cited_sources=list(data.get("cited_sources") or []),
        judge_model=judge_model,
        judge_prompt_hash=judge_prompt_hash(prompt_version),
    )


async def score_answer(
    brand_name: str,
    aliases: list[str],
    answer_text: str,
    judge_model: str | None = None,
    prompt_version: str = CURRENT_JUDGE_PROMPT_VERSION,
) -> ScoreResult:
    """Run the judge over a single answer and return a ``ScoreResult``.

    The actual judge model invocation is stubbed for the scaffold; the system
    prompt and user message are fully assembled so wiring a provider is a
    one-liner.
    """

    judge_model = judge_model or settings.default_judge_model
    system_prompt = get_judge_prompt(prompt_version)  # noqa: F841 - used once live
    user_message = build_judge_user_message(brand_name, aliases, answer_text)  # noqa: F841

    # TODO: call the judge model with (system_prompt, user_message), then:
    #   return parse_judge_output(response_text, judge_model, prompt_version)
    raise NotImplementedError("score_answer is a scaffold stub")
