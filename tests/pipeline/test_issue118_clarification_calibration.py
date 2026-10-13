"""Paired real-provider calibration replay for Issue #118.

Run explicitly with ISSUE118_LIVE_REPLAY=1 and provider credentials. No model
decision or retrieval result is supplied by this test: both prompt versions are
sent to the configured task-understanding provider. Authority eligibility is
separate and fail-closed; an unverified case never enters the AC1 denominator.
"""

import asyncio
import json
import os
import subprocess
from collections import Counter

import pytest

from backend.llm.deepseek import DeepseekProvider
from backend.pipeline import task_understanding as task_module
from backend.pipeline.task_understanding import understand_task

BASELINE = "b4be4da"

# Frozen calibration cases. These are deliberately marked no-authority until an
# exact, reviewed official corpus source is mapped to the claim being tested.
# The presence of an answerable-sounding query is not evidence of authority.
CASES = (
    ("en_subscription", "Is there a subscription fee?", "positive", None),
    ("en_australia", "where to buy in australia", "positive", None),
    ("en_night_vision", "I need night vision x2", "positive", None),
    ("zh_compare", "分辨率最高的产品是哪个？价格如何？", "positive", None),
    ("en_vehicle", "how to hide this inside a vehicle?", "positive", None),
    ("en_selector", "Which product fits my project?", "negative", None),
    ("zh_revision", "这台设备应该刷哪个硬件版本？", "negative", None),
    ("zh_deixis", "这个设备支持什么？", "negative", None),
)


def _baseline_prompt() -> str:
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:backend/pipeline/task_understanding.py"],
        text=True,
    )
    marker = "_UNDERSTANDING_PROMPT = \"\"\""
    start = source.index(marker) + len(marker)
    end = source.index('\n"""', start)
    return source[start:end]


def _provider() -> DeepseekProvider:
    required = ("DEEPSEEK_API_BASE", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip("live replay requires provider settings: " + ", ".join(missing))
    return DeepseekProvider(
        provider_id="issue118-replay",
        api_base=os.environ["DEEPSEEK_API_BASE"],
        api_key=os.environ["DEEPSEEK_API_KEY"],
        model=os.environ["DEEPSEEK_MODEL"],
        temperature=0,
    )


@pytest.mark.integration
def test_issue118_paired_prompt_replay_reports_decisions_and_authority_buckets():
    """Use actual structured task_understanding responses, never scripted modes."""
    if os.getenv("ISSUE118_LIVE_REPLAY") != "1":
        pytest.skip("set ISSUE118_LIVE_REPLAY=1 to call the configured real provider")

    provider = _provider()
    candidate_prompt = task_module._UNDERSTANDING_PROMPT
    prompts = (("before", _baseline_prompt()), ("after", candidate_prompt))
    decisions: dict[str, dict[str, str]] = {name: {} for name, _ in prompts}

    async def run_one(prompt_name: str, prompt: str, case_id: str, query: str) -> None:
        task_module._UNDERSTANDING_PROMPT = prompt
        result = await understand_task(query, None, provider)
        decisions[prompt_name][case_id] = result.interaction_mode
        assert result.parse_ok, f"{prompt_name}/{case_id}: provider did not return structured JSON"
        if any("\u4e00" <= char <= "\u9fff" for char in query):
            assert any("\u4e00" <= char <= "\u9fff" for char in result.extracted_query)
            assert any("\u4e00" <= char <= "\u9fff" for char in result.rewritten_query)
        else:
            assert any(char.isascii() and char.isalpha() for char in result.extracted_query)
            assert any(char.isascii() and char.isalpha() for char in result.rewritten_query)
        assert (result.category == "off_topic") == (result.interaction_mode == "off_topic")
        if not any(token in query for token in ("NE101", "NE301", "NE302", "NE503")):
            assert not any(
                token in result.extracted_query or token in result.rewritten_query
                for token in ("NE101", "NE301", "NE302", "NE503")
            ), f"{prompt_name}/{case_id}: model introduced an unsupported product identity"

    async def replay() -> None:
        for prompt_name, prompt in prompts:
            for case_id, query, _, _ in CASES:
                await run_one(prompt_name, prompt, case_id, query)

    original_prompt = task_module._UNDERSTANDING_PROMPT
    try:
        asyncio.run(replay())
    finally:
        task_module._UNDERSTANDING_PROMPT = original_prompt

    summary = {}
    for prompt_name, _ in prompts:
        by_kind: dict[str, list[str]] = {"positive": [], "negative": [], "no_authority": []}
        for case_id, _, kind, authority_ref in CASES:
            bucket = "negative" if kind == "negative" else (
                "positive" if authority_ref else "no_authority"
            )
            by_kind[bucket].append(decisions[prompt_name][case_id])
        positive = by_kind["positive"]
        negative = by_kind["negative"]
        summary[prompt_name] = {
            "authority_supported_positive_n": len(positive),
            "positive_standard_rate": (
                sum(mode == "standard" for mode in positive) / len(positive) if positive else None
            ),
            "necessary_clarification_n": len(negative),
            "negative_clarification_rate": (
                sum(mode == "clarification_required" for mode in negative) / len(negative)
                if negative
                else None
            ),
            "no_authority_n": len(by_kind["no_authority"]),
            "no_authority_modes": dict(Counter(by_kind["no_authority"])),
        }

    print(json.dumps({"before_after": summary, "decisions": decisions}, ensure_ascii=False))
    # This calibration set has no authority mappings yet. Refuse to imply AC1
    # was measured from answerable-looking but unsupported cases.
    assert all(row["authority_supported_positive_n"] == 0 for row in summary.values())
    assert all(row["positive_standard_rate"] is None for row in summary.values())


@pytest.mark.unit
def test_frozen_calibration_cases_cover_bilingual_positive_and_clarification_intents():
    assert {kind for _, _, kind, _ in CASES} == {"positive", "negative"}
    assert any(any("a" <= char.lower() <= "z" for char in query) for _, query, _, _ in CASES)
    assert any(any("\u4e00" <= char <= "\u9fff" for char in query) for _, query, _, _ in CASES)
    assert all(authority_ref is None for _, _, _, authority_ref in CASES)
