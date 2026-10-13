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
    """Small deterministic answer adapter with a pre-contract failure mode."""

    def __init__(self, expected_answer):
        self.expected_answer = expected_answer
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

        system = messages[0]["content"]
        # Model behavior is held constant and deterministic: without the
        # answer contract it reproduces the old unqualified synthesis. With
        # the contract, it emits this scenario's controlled model response.
        if "## Applicability-first hardware response" not in system:
            return _response("TF_PWR 是 GPIO42；4G 与 TF 卡不能同时使用。[1]")
        return _response(self.expected_answer)


def _rag(sources, expected_answer):
    searcher = MagicMock()
    searcher.search.return_value = list(sources)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda _q, results, _k: list(results)
    reranker.rerank_scored.side_effect = lambda _q, results, **_kwargs: (list(results), [])
    llm = _HardwareReplayModel(expected_answer)
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="base",
        min_results_to_answer=1,
    )
    return rag, llm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "answer"),
    [
        (
            "4G 模块和 TF 卡有没有引脚冲突，能一起用吗？",
            (
                "NE101：V1.0–V1.2 的 TF_PWR 是 GPIO42；V2.0 改为 GPIO48，"
                "且与 Cat-1/HaLow 模组供电共用，GPIO42 是 CAM_PWR。[1] "
                "NE301：4G 走 USB，与 TF 引脚无复用。[2] 请按具体产品和版本确认。"
            ),
        ),
        (
            "Can I use the 4G module and TF card at the same time?",
            (
                "NE101: V1.0–V1.2 TF_PWR is GPIO42; V2.0 uses GPIO48, shared with the "
                "Cat-1/HaLow module supply, while GPIO42 is CAM_PWR.[1] NE301: 4G uses USB "
                "with no TF pin multiplexing.[2] Confirm the exact product and revision."
            ),
        ),
    ],
)
async def test_unknown_product_replay_conditions_family_and_excludes_cross_family_case(query, answer):
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
    rag, llm = _rag([ne101, ne301, case], answer)

    result = await rag.answer(query)

    assert "NE101" in result.answer and "NE301" in result.answer
    assert "V1.0–V1.2" in result.answer and "V2.0" in result.answer
    assert "GPIO48" in result.answer and "CAM_PWR" in result.answer
    assert "共用" in result.answer or "shared" in result.answer.lower()
    assert "USB" in result.answer
    assert "无复用" in result.answer or "no TF pin multiplexing" in result.answer
    assert "[1]" in result.answer and "[2]" in result.answer
    source_urls = {source["url"] for source in result.sources}
    assert ne101.url in source_urls and ne301.url in source_urls
    assert case.url not in source_urls
    generation = [call for call in llm.calls if call[0] == "generation"]
    assert len(generation) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "answer"),
    [
        (
            "NE101 V1.2 的 TF_PWR 是什么引脚？",
            "NE101 V1.0–V1.2 的 TF_PWR 为 GPIO42。[1]",
        ),
        (
            "NE101 V2.0 的 TF 卡供电怎么接？",
            (
                "NE101 V2.0 的 TF_PWR_ON 为 GPIO48；它与 Cat-1/HaLow 模组供电使能共用。"
                "该版本 GPIO42 是 CAM_PWR，不能把 GPIO42 当作 TF_PWR。[1]"
            ),
        ),
        (
            "How does NE101 V2.0 power the TF card?",
            (
                "On NE101 V2.0, TF_PWR_ON is GPIO48 and shares the Cat-1/HaLow module supply. "
                "GPIO42 is CAM_PWR on this revision, not TF power.[1]"
            ),
        ),
    ],
)
async def test_revision_answer_cites_version_qualified_hardware_source_only(query, answer):
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
    rag, _llm = _rag([qualified, unscoped], answer)

    result = await rag.answer(query)

    assert answer.split("[1]")[0].strip() in result.answer
    assert "[1]" in result.answer
    if "V2.0" in query:
        assert "GPIO48" in result.answer
        assert "GPIO42" in result.answer and "CAM_PWR" in result.answer
    assert result.sources[0]["url"] == qualified.url
    cited_numbers = {int(value) for value in re.findall(r"\[(\d+)\]", result.answer)}
    assert cited_numbers == {1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "answer"),
    [
        (
            "NE101 的 4G Cat-1 和 TF 卡能否同时使用？",
            "NE101 的限制取决于具体 Cat-1/HaLow 配置：复用 GPIO38–GPIO41 和 GPIO45 的冲突配置不能并用；GPIO41 也与 TF/HaLow 使用冲突。[1]",
        ),
        (
            "Can NE101 Cat-1 4G and the TF card be used together?",
            "On NE101 this depends on the selected Cat-1/HaLow configuration: only combinations conflicting on multiplexed GPIO38–GPIO41/GPIO45 cannot be used together; GPIO41 also conflicts with TF/HaLow use.[1]",
        ),
    ],
)
async def test_conflicting_example_does_not_turn_configuration_limit_into_universal_conflict(
    query, answer,
):
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
    rag, _llm = _rag([authoritative, old_example], answer)

    result = await rag.answer(query)

    assert "取决于具体" in result.answer or "depends on the selected" in result.answer
    assert "GPIO45" in result.answer and "GPIO41" in result.answer
    assert "所有配置" not in result.answer and "all configurations" not in result.answer.lower()
    assert "不能同时使用" not in result.answer
    if "On NE101" in result.answer:
        assert "cannot be used together" in result.answer
    else:
        assert "冲突配置不能并用" in result.answer
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
    answer = "For FixtureBoard Rev B, use connector J7.[1]"
    rag, _llm = _rag([source], answer)

    result = await rag.answer("FixtureBoard Rev B sensor connector?")

    assert "Rev B" in result.answer and "J7" in result.answer
    assert "J3" not in result.answer
    assert "[1]" in result.answer
    assert result.sources[0]["url"] == source.url
