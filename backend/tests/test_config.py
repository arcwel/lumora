"""Tests for snapshot model configuration parsing."""

from __future__ import annotations

from app.config import Settings


def test_snapshot_model_list_parses_and_dedupes():
    s = Settings(snapshot_models="gpt-4o-mini, claude-haiku-4-5-20251001 ,gpt-4o-mini,")
    assert s.snapshot_model_list == ["gpt-4o-mini", "claude-haiku-4-5-20251001"]


def test_snapshot_model_list_empty():
    assert Settings(snapshot_models="").snapshot_model_list == []


def test_runs_per_prompt_default():
    assert Settings().runs_per_prompt == 3
