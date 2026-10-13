"""Issue #122 frozen hardware-compatibility behavior replays.

These deterministic replays run through the real RAG answer path, including
product qualification, citation-context construction, and citation validation.
The controlled model adapter makes the final answer reproducible without a
network model; assertions are on answer text and the sources it actually cites.
"""

import json
import re
from unittest.mock import MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult


def _source(*, text, source_id, product="ne101", source_type="github", url=None, score=0.9):
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title=source_id.rsplit("/", 1)[-1],
        url=url or f"https://docs.example/{source_id}",
        score=score,
        chunk_index=0,
    )


def _response(content):
    return LLMResponse(
        content=content, model="issue122-controlled-replay", tokens_input=1,
        tokens_output=1, latency_ms=0,
    )


class _HardwareReplayModel:
    """Deterministic adapter that derives claims only from citable evidence."""

    def __init__(self):
        self.calls = []

    async def generate(self, messages, *, task, **_kwargs):
        self.calls.append((task, messages))
        if task == "task_understanding":
            query = messages[-1]["content"].split("## 用户输入\n", 1)[-1]
            return _response(json.dumps({
                "category": "support",
                "reason": "hardware compatibility replay",
                "confidence": 1,
                "interaction_mode": "standard",
                "evidence_intent": "factual",
                "extracted_query": query,
                "rewritten_query": query,
            }, ensure_ascii=False))

        user = messages[-1]["content"]
        context = user.split("## 可引用资料\n", 1)[-1].split(
            "\n\n## 背景资料", 1
        )[0].split("\n\n## 问题", 1)[0]
        blocks = re.split(r"(?m)^\[(\d+)\] ", context)
        eligible = []
        query = user.split("## 问题\n", 1)[-1].split("\n\n## 要求", 1)[0].lower()
        requested_revision = re.search(
            r"(?:v|rev)\s*([0-9]+(?:\.[0-9]+)*|[a-z])", query
        )
        revision = requested_revision.group(1) if requested_revision else None
        requested_family = re.search(r"\b(ne\d{3,4})\b", query)
        family = requested_family.group(1) if requested_family else None
        for number, block in zip(blocks[1::2], blocks[2::2]):
            body = block.split("\n\n", 1)[-1]
            body_lower = body.lower()
            if family and family not in body_lower:
                continue
            revision_marker = (
                rf"\brev\s*{re.escape(revision)}\b"
                if revision and revision.isalpha()
                else rf"\bv\s*{re.escape(revision)}\b" if revision else None
            )
            if revision and not re.search(revision_marker, body_lower):
                continue
            # A pin assertion assigned to a different revision is tainted for
            # this replay; it may not support the queried hardware fact.
            if revision == "2.0" and re.search(r"v\s*2\.0[^;\n]*gpio\s*42", body_lower):
                continue
            eligible.append((int(number), body.strip()))

        if not eligible:
            return _response("I couldn't find relevant information in the official sources.")

        # Conflicting instructions for the requested revision cannot both be
        # selected. Preserve the highest-ranked citable source only.
        selected = eligible[:1] if revision else eligible
        statements = []
        for number, body in selected:
            if revision:
                body = ". ".join(
                    sentence
                    for sentence in re.split(r"\.\s+|;\s+", body)
                    if re.search(revision_marker, sentence.lower())
                )
            statements.append(f"{body} [{number}]")
        return _response(" ".join(statements))


def _rag(sources):
    searcher = MagicMock()
    searcher.search.return_value = list(sources)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda _q, results, _k: list(results)
    reranker.rerank_scored.side_effect = lambda _q, results, **_kwargs: (list(results), [])
    llm = _HardwareReplayModel()
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="base",
        min_results_to_answer=1,
    )
    return rag, llm


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "4G 模块和 TF 卡有没有引脚冲突，能一起用吗？",
    "Can I use the 4G module and TF card at the same time?",
])
async def test_unknown_product_replay_conditions_family_and_excludes_cross_family_case(query):
    ne101 = _source(
        text="NE101 TF power: V1.0-V1.2 GPIO42; V2.0 GPIO48, shared with Cat-1/HaLow supply. V2.0 GPIO42 is CAM_PWR.",
        source_id="wiki/neoeyes-ne101/hardware-connection.md",
    )
    ne301 = _source(
        text="NE301 EG912 4G connects over USB and does not share TF/SDMMC pins.",
        source_id="wiki/neoeyes-ne301/usb.md",
        product="ne301",
        url="https://docs.example/wiki/neoeyes-ne301/usb.md",
    )
    case = _source(
        text="Historical NE301 case: J11-J15 USB wiring.",
        source_id="knowledge-cases/support/ne301-usb.md",
        product="ne301",
        source_type="filesystem",
        url="",
    )
    rag, llm = _rag([ne101, ne301, case])

    result = await rag.answer(query)

    assert "NE101" in result.answer and "NE301" in result.answer
    assert "V1.0-V1.2" in result.answer and "V2.0" in result.answer
    assert "GPIO48" in result.answer and "CAM_PWR" in result.answer
    assert "shared" in result.answer.lower()
    assert "USB" in result.answer
    assert "does not share TF/SDMMC pins" in result.answer
    assert "[1]" in result.answer and "[2]" in result.answer
    source_urls = {source["url"] for source in result.sources}
    assert ne101.url in source_urls and ne301.url in source_urls
    assert case.url not in source_urls
    generation = [call for call in llm.calls if call[0] == "generation"]
    assert len(generation) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "NE101 V1.2 的 TF_PWR 是什么引脚？",
    "NE101 V2.0 的 TF 卡供电怎么接？",
    "How does NE101 V2.0 power the TF card?",
])
async def test_revision_answer_cites_version_qualified_hardware_source_only(query):
    qualified = _source(
        text="NE101 TF_PWR: V1.0-V1.2 GPIO42. NE101 V2.0: TF_PWR_ON GPIO48; GPIO48 shared with Cat-1/HaLow module supply. GPIO42 is CAM_PWR.",
        source_id="wiki/neoeyes-ne101/hardware-connection.md",
        url="https://docs.example/neoeyes-ne101/hardware-connection.md",
        score=0.95,
    )
    unscoped = _source(
        text="Example: set TF_PWR to GPIO42 before SD_MMC.begin; 4G cannot be used at the same time.",
        source_id="wiki/neoeyes-ne101/6-example-arduino.md",
        url="https://docs.example/neoeyes-ne101/6-example-arduino.md",
        score=0.8,
    )
    rag, _llm = _rag([qualified, unscoped])

    result = await rag.answer(query)

    assert "[1]" in result.answer
    if "V2.0" in query:
        assert "GPIO48" in result.answer
    assert result.sources[0]["url"] == qualified.url
    cited_numbers = {int(value) for value in re.findall(r"\[(\d+)\]", result.answer)}
    assert cited_numbers == {1}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "NE101 的 4G Cat-1 和 TF 卡能否同时使用？",
    "Can NE101 Cat-1 4G and the TF card be used together?",
])
async def test_conflicting_example_does_not_turn_configuration_limit_into_universal_conflict(query):
    authoritative = _source(
        text="NE101 hardware connection: GPIO38-GPIO41 and GPIO45 are multiplexed. Only conflicting WiFi-HaLow or 4G Cat-1 configurations cannot be used together; assess the selected configuration. GPIO41 conflicts with TF/HaLow use.",
        source_id="wiki/neoeyes-ne101/hardware-connection.md",
        url="https://docs.example/neoeyes-ne101/hardware-connection.md",
        score=0.95,
    )
    old_example = _source(
        text="Example guide: 4G and TF cannot be used simultaneously.",
        source_id="wiki/neoeyes-ne101/6-example-arduino.md",
        url="https://docs.example/neoeyes-ne101/6-example-arduino.md",
        score=0.8,
    )
    rag, _llm = _rag([authoritative, old_example])

    result = await rag.answer(query)

    assert "assess the selected configuration" in result.answer
    assert "GPIO45" in result.answer and "GPIO41" in result.answer
    assert "所有配置" not in result.answer and "all configurations" not in result.answer.lower()
    assert "Only conflicting" in result.answer
    assert "Example guide" not in result.answer
    assert "[1]" in result.answer
    assert result.sources[0]["url"] == authoritative.url


@pytest.mark.asyncio
async def test_revision_scope_replay_handles_non_pin_fact_without_product_specific_rule():
    source = _source(
        text="FixtureBoard Rev A sensor connector is J3. FixtureBoard Rev B sensor connector is J7.",
        source_id="fixture-board/hardware/revisions.md",
        product="hardware-common",
        url="https://docs.example/fixture-board/revisions.md",
    )
    rag, _llm = _rag([source])

    result = await rag.answer("FixtureBoard Rev B sensor connector?")

    assert "Rev B" in result.answer and "J7" in result.answer
    assert "J3" not in result.answer
    assert "[1]" in result.answer
    assert result.sources[0]["url"] == source.url


@pytest.mark.asyncio
async def test_tainted_revision_source_must_not_support_ne101_gpio42_claim():
    """RED:现有预写答案会引用把 V2.0 GPIO42 错归 NE101 的语料。"""
    wrong_revision = _source(
        text="NE101 V2.0 TF_PWR is GPIO42.",
        source_id="wiki/neoeyes-ne101/incorrect-revision.md",
    )
    rag, _llm = _rag([wrong_revision])

    result = await rag.answer("NE101 V2.0 TF_PWR 是什么引脚？")

    assert "GPIO42" not in result.answer
    assert "[1]" not in result.answer


@pytest.mark.asyncio
async def test_conflicting_revision_instructions_do_not_both_enter_citation_context():
    """RED:冲突版本指令不应作为同一答案的双侧依据。"""
    conflict_a = _source(
        text="NE101 V2.0 TF_PWR is GPIO48.",
        source_id="wiki/neoeyes-ne101/revision-a.md",
    )
    conflict_b = _source(
        text="NE101 V2.0 TF_PWR is GPIO42.",
        source_id="wiki/neoeyes-ne101/revision-b.md",
    )
    rag, _llm = _rag(
        [conflict_a, conflict_b],
    )

    result = await rag.answer("NE101 V2.0 TF_PWR 是什么引脚？")

    assert not ("GPIO48" in result.answer and "GPIO42" in result.answer)
    assert {int(n) for n in re.findall(r"\[(\d+)\]", result.answer)}.issubset({1})


@pytest.mark.asyncio
async def test_cross_family_source_cannot_support_ne101_fact():
    """RED:跨家族来源不能支撑 NE101 硬件事实。"""
    ne301 = _source(
        text="NE301 TF_PWR uses GPIO42.",
        source_id="wiki/neoeyes-ne301/hardware.md",
        product="ne301",
    )
    rag, _llm = _rag([ne301])

    result = await rag.answer("NE101 TF_PWR 是什么引脚？")

    assert "GPIO42" not in result.answer
    assert not result.is_answered


@pytest.mark.asyncio
async def test_scored_rerank_fallback_rejects_hardware_source_for_wrong_revision():
    source = _source(
        text="NE101 V1.2 TF_PWR is GPIO42.",
        source_id="wiki/neoeyes-ne101/hardware.md",
    )
    rag, llm = _rag([source])
    rag._reranker.threshold = 0.3
    rag._reranker.rerank_scored.side_effect = lambda _q, results, **_kwargs: (
        [], [(candidate, 0.1) for candidate in results]
    )

    result = await rag.answer("NE101 V2.0 TF_PWR 是什么引脚？")

    assert not result.is_answered
    assert result.sources == []
    assert not any(task == "generation" for task, _messages in llm.calls)
