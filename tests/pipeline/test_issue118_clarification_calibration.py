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

# Frozen calibration cases. Every positive carries an authority_ref verified
# against the publicly authorized official sources on 2026-10-13 (issue #118
# R3 bounded recovery). Mapping rationale:
# - en_subscription: official purchase model — terms-of-service pricing clause
#   ("Prices are listed in USD", one-time checkout) plus the store catalog where
#   every product is a one-time-priced item and no official page advertises a
#   subscription fee. The honest grounded answer is one-time hardware purchase.
# - en_australia: https://www.camthink.ai/shipping-policy/ — worldwide DAP
#   delivery (DHL/FedEx/SF/Yuntu/Yanwen/4PX); the "online checkout not
#   available" exclusion list covers parts of South America/Asia/Africa but
#   does NOT include Australia.
# - en_night_vision: NE503 wiki overview — "<0.01 LUX full-color night vision",
#   automatic IR-CUT switching, "IR fill light (supported, 80m)"; store page
#   corroborates 4K UHD + 0.01-lux low-light imaging.
# - zh_compare: cross-product resolution comparison grounded in the official
#   spec pages — NE503 4K UHD (IMX678, 3856x2180) vs NE301 (OS04C10, 4MP) vs
#   NE302 (4MP CMOS) vs NE101 (OV5640 module); price from the NE503 store page
#   ($999–$1,199).
# - en_vehicle: official installation material — store mounting brackets
#   (wall/dial/pole/shaft&ball/base) for NE101/NE301 and the wiki dev-kit
#   installation guide. No official covert-installation guide exists; the
#   expected honest answer states that absence explicitly instead of guessing.
# The presence of an answerable-sounding query is not evidence of authority:
# an empty authority_ref keeps a positive out of the AC1 denominator
# (fail-closed) and buckets it as no_authority.
CASES = (
    (
        "en_subscription",
        "Is there a subscription fee?",
        "positive",
        "https://www.camthink.ai/terms-of-service/",
    ),
    (
        "en_australia",
        "where to buy in australia",
        "positive",
        "https://www.camthink.ai/shipping-policy/",
    ),
    (
        "en_night_vision",
        "I need night vision x2",
        "positive",
        "https://wiki.camthink.ai/docs/neoeyes-ne503-series/overview",
    ),
    (
        "zh_compare",
        "分辨率最高的产品是哪个？价格如何？",
        "positive",
        "https://wiki.camthink.ai/docs/neoeyes-ne503-series/overview",
    ),
    (
        "en_vehicle",
        "how to hide this inside a vehicle?",
        "positive",
        "https://www.camthink.ai/store/mounting-ne101/",
    ),
    ("en_selector", "Which product fits my project?", "negative", None),
    ("zh_revision", "这台设备应该刷哪个硬件版本？", "negative", None),
    ("zh_deixis", "这个设备支持什么？", "negative", None),
)

# AC1 gate: >= 90% of authority-supported generic-answerable first questions
# must route to retrieval instead of unconditional model clarification.
AC1_POSITIVE_STANDARD_GATE = 0.9

_OFFICIAL_AUTHORITY_HOSTS = ("https://wiki.camthink.ai/", "https://www.camthink.ai/")


def _baseline_prompt() -> str:
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:backend/pipeline/task_understanding.py"],
        text=True,
    )
    marker = '_UNDERSTANDING_PROMPT = """'
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
            bucket = (
                "negative"
                if kind == "negative"
                else ("positive" if authority_ref else "no_authority")
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
    # AC1 (measured, not prescribed): on the frozen authority-qualified EN/ZH
    # calibration set the candidate prompt must route >= 90% of the positives
    # to retrieval, and the paired baseline must show the pre-fix over-
    # clarification it claims to fix (strict improvement, AC3).
    for prompt_name, row in summary.items():
        assert row["authority_supported_positive_n"] == sum(
            kind == "positive" for _, _, kind, ref in CASES if ref
        ), f"{prompt_name}: authority mapping drifted out of the AC1 denominator"
        assert row["no_authority_n"] == sum(
            1 for _, _, kind, ref in CASES if kind == "positive" and not ref
        ), f"{prompt_name}: unmapped positives must stay in the separate no-authority bucket"
    before_rate = summary["before"]["positive_standard_rate"]
    after_rate = summary["after"]["positive_standard_rate"]
    assert before_rate is not None and after_rate is not None, "replay produced no positive rate"
    assert after_rate >= AC1_POSITIVE_STANDARD_GATE, (
        f"AC1 unmet: candidate positive_standard_rate {after_rate:.2f} < {AC1_POSITIVE_STANDARD_GATE}"
    )
    assert after_rate > before_rate, (
        f"AC3 unmet: candidate rate {after_rate:.2f} does not improve on baseline {before_rate:.2f}"
    )
    # AC2: the frozen indispensable-clarification negatives must still clarify
    # under the candidate prompt (no forced disguise as grounded answers).
    assert summary["after"]["negative_clarification_rate"] == 1.0, (
        "AC2 unmet: a frozen negative lost its necessary clarification: "
        + json.dumps(summary["after"], ensure_ascii=False)
    )


@pytest.mark.unit
def test_frozen_calibration_cases_cover_bilingual_positive_and_clarification_intents():
    assert {kind for _, _, kind, _ in CASES} == {"positive", "negative"}
    assert any(any("a" <= char.lower() <= "z" for char in query) for _, query, _, _ in CASES)
    assert any(any("\u4e00" <= char <= "\u9fff" for char in query) for _, query, _, _ in CASES)
    # Fail-closed authority eligibility: every mapped positive must cite a
    # publicly authorized official source; an empty ref never enters AC1.
    assert all(
        authority_ref and any(authority_ref.startswith(host) for host in _OFFICIAL_AUTHORITY_HOSTS)
        for _, _, kind, authority_ref in CASES
        if kind == "positive"
    ), "every AC1 positive must map to an official camthink authority source"
