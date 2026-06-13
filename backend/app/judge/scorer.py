"""LLM-as-judge scoring pipeline.

Takes a raw answer plus brand context and produces a structured ``ScoreResult``
that maps directly onto the ``Score`` model. The vendor judge call is stubbed
for the scaffold; ``parse_judge_output`` is real so the contract is testable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.config import settings
from app.judge.rubric import (
    CURRENT_JUDGE_PROMPT_VERSION,
    get_judge_prompt,
    judge_prompt_hash,
)
from app.models.score import Sentiment
from app.providers import ProviderError, provider_for_model

logger = logging.getLogger(__name__)

_VALID_SENTIMENTS = {s.value for s in Sentiment}

#: How many times to re-query the judge when it returns unparseable JSON.
DEFAULT_JUDGE_MAX_RETRIES = 2


@dataclass(slots=True)
class ScoreResult:
    """Structured judgement, ready to persist as a ``Score`` row."""

    brand_mentioned: bool
    mention_position: int | None
    sentiment: Sentiment | None
    cited_sources: list[str] = field(default_factory=list)
    judge_model: str = ""
    judge_prompt_hash: str = ""
    #: Tokens the judge call itself consumed (for budget accounting); not persisted on Score.
    judge_token_count: int | None = None


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
    max_retries: int = DEFAULT_JUDGE_MAX_RETRIES,
) -> ScoreResult:
    """Run the judge over a single answer and return a ``ScoreResult``.

    Calls the configured judge model (defaulting to the cheapest available
    Haiku-class model) with the pinned rubric, then parses the strict-JSON
    response. The ``judge_model`` and ``judge_prompt_hash`` are recorded on the
    result for reproducibility. Unparseable JSON is retried up to
    ``max_retries`` times before giving up.
    """

    judge_model = judge_model or settings.default_judge_model
    provider = provider_for_model(judge_model)
    system_prompt = get_judge_prompt(prompt_version)
    user_message = build_judge_user_message(brand_name, aliases, answer_text)

    # BaseProvider.query takes a single prompt; fold the rubric (system) and the
    # answer payload (user) into one message to stay vendor-agnostic.
    full_prompt = f"{system_prompt}\n\n{user_message}"

    last_error: ValueError | None = None
    for attempt in range(max_retries + 1):
        response = await provider.query(full_prompt)
        try:
            result = parse_judge_output(response.text, judge_model, prompt_version)
            result.judge_token_count = response.token_count
            return result
        except ValueError as exc:
            last_error = exc
            logger.warning(
                "Judge returned invalid JSON (attempt %d/%d) on model %s: %s",
                attempt + 1,
                max_retries + 1,
                judge_model,
                exc,
            )

    raise ProviderError(
        f"Judge model {judge_model!r} did not return valid JSON after "
        f"{max_retries + 1} attempts: {last_error}"
    )
