"""Answer and SSE stream must apply the same bounded hardware revision gate."""

import json

import pytest

from tests.pipeline.test_issue122_hardware_replay import _rag, _source


class _StreamingHardwareReplayModel:
    """Adapt the frozen replay model to the public stream path."""

    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = wrapped.calls
        self.generation_contexts = []

    async def generate(self, *args, **kwargs):
        return await self.wrapped.generate(*args, **kwargs)

    async def stream(self, messages, *, task, **kwargs):
        if task == "generation":
            self.generation_contexts.append(messages[-1]["content"])
        response = await self.wrapped.generate(messages, task=task, **kwargs)
        yield response.content


async def _stream_events(rag, query):
    return [json.loads(event) async for event in rag.stream_answer(query)]


@pytest.mark.asyncio
async def test_answer_and_stream_revision_evidence_parity_including_shared_taxonomy_source():
    query = "NE101 V2.0 的 TF_PWR 是什么引脚？"
    wrong = _source(
        text="NE101 V1.2 TF_PWR is GPIO42.",
        source_id="wiki/neoeyes-ne101/v1-only.md",
        score=0.99,
    )
    valid = _source(
        text="NE101 V2.0 TF_PWR_ON is GPIO48.",
        source_id="wiki/neoeyes-ne101/v2.md",
        score=0.90,
    )
    common = _source(
        text="NE101 hardware-common guide: NE101 V2.0 TF connector uses GPIO48.",
        source_id="hardware-common/ne101-revision-guide.md",
        product="hardware-common",
        score=0.85,
    )
    answer_rag, _ = _rag([wrong, valid, common])
    stream_rag, stream_model = _rag([wrong, valid, common])
    stream_model = _StreamingHardwareReplayModel(stream_model)
    stream_rag._llm = stream_model

    answer = await answer_rag.answer(query)
    events = await _stream_events(stream_rag, query)
    sources_event = next(event for event in events if event["type"] == "sources")
    complete = next(event for event in events if event["type"] == "complete")
    exposed_ids = {source["url"] for source in sources_event["sources"]}

    assert wrong.url not in exposed_ids
    assert exposed_ids == {source["url"] for source in answer.sources}
    assert "GPIO42" not in answer.answer
    assert "GPIO42" not in complete["answer"]
    assert wrong.text not in stream_model.generation_contexts[0]
    assert {valid.url, common.url} <= exposed_ids


@pytest.mark.asyncio
async def test_stream_revision_filter_blocks_generation_when_only_wrong_revision_source_exists():
    query = "NE101 V2.0 的 TF_PWR 是什么引脚？"
    wrong = _source(
        text="NE101 V1.2 TF_PWR is GPIO42.",
        source_id="wiki/neoeyes-ne101/v1-only.md",
    )
    rag, model = _rag([wrong])
    stream_model = _StreamingHardwareReplayModel(model)
    rag._llm = stream_model

    events = await _stream_events(rag, query)

    assert not stream_model.generation_contexts
    assert not [event for event in events if event["type"] == "sources"]
    complete = next(event for event in events if event["type"] == "complete")
    assert complete["sources"] == []
    assert complete["is_answered"] is False
