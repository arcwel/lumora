#!/usr/bin/env python
"""Smoke-test the live provider adapters and the LLM-as-judge pipeline.

Reads API keys from the environment / ``.env`` (see ``.env.example``). For each
provider with a key configured, it sends one tiny prompt and prints the response
text and token count. Providers without a key are skipped, not failed — so this
is safe to run in CI or locally with only a subset of keys.

Usage (from the ``backend`` directory, with the venv active)::

    python scripts/smoke_providers.py
    python scripts/smoke_providers.py --judge   # also exercise score_answer
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as a plain script: put the backend root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers import (  # noqa: E402
    PROVIDER_REGISTRY,
    ProviderError,
    get_provider,
)

_PROMPT = "In one short sentence, name a popular open-source database."


async def _check_provider(name: str) -> bool:
    """Query one provider. Returns True on success, False on skip/failure."""

    provider = get_provider(name)
    if not provider.is_configured():
        print(f"  [skip] {name}: no API key configured")
        return False

    print(f"  [....] {name} ({provider.model}): querying…")
    try:
        result = await provider.query(_PROMPT)
    except ProviderError as exc:
        print(f"  [FAIL] {name}: {exc}")
        return False

    preview = result.text.replace("\n", " ")
    if len(preview) > 100:
        preview = preview[:100] + "…"
    print(f"  [ ok ] {name}: tokens={result.token_count} | {preview}")
    return True


async def _check_judge() -> bool:
    """Exercise the end-to-end judge pipeline on a synthetic answer."""

    from app.judge.scorer import score_answer

    answer = (
        "For agencies, popular project management tools include Asana, "
        "Monday.com, and ClickUp. Asana is especially well-regarded."
    )
    print("  [....] judge: scoring a synthetic answer…")
    try:
        result = await score_answer(
            brand_name="Asana",
            aliases=["Asana Inc."],
            answer_text=answer,
        )
    except ProviderError as exc:
        print(f"  [FAIL] judge: {exc}")
        return False

    print(
        f"  [ ok ] judge ({result.judge_model}): "
        f"mentioned={result.brand_mentioned} position={result.mention_position} "
        f"sentiment={result.sentiment} hash={result.judge_prompt_hash[:12]}…"
    )
    return True


async def _main(run_judge: bool) -> int:
    print("Provider smoke test\n-------------------")
    results = [await _check_provider(name) for name in PROVIDER_REGISTRY]

    if run_judge:
        print("\nJudge pipeline\n--------------")
        results.append(await _check_judge())

    succeeded = sum(results)
    print(f"\n{succeeded}/{len(results)} check(s) succeeded.")
    # Exit non-zero only if a configured check actually failed (skips are fine).
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Also run the end-to-end judge scoring pipeline.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.judge)))


if __name__ == "__main__":
    main()
