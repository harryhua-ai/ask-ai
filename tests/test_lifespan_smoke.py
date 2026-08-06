"""lifespan 启动冒烟测试。

回归覆盖 C1：重构把 db_config 移进 _build_llm_state 后，lifespan 仍引用
db_config → NameError 启动必崩。ASGITransport 不触发 lifespan（admin API
测试用它绕过 lifespan，手动初始化 app.state），故该路径此前零覆盖。

本测试真正跑 lifespan，mock 掉 GPU/模型/网络重依赖（weaviate、BGE embedder/
reranker），DB 连测试库（TEST_DATABASE_URL），确保启动路径可执行且
app.state.llm / app.state.rag 正确接线。
"""

import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_api_base_requires_https_in_prod(monkeypatch):
    """prod 模式不得通过明文 HTTP 发送 LLM 凭证。"""
    from backend.api.admin.schemas import validate_llm_api_base

    monkeypatch.setenv("APP_MODE", "prod")
    monkeypatch.delenv("LLM_ALLOWED_HOSTS", raising=False)

    with pytest.raises(ValueError, match="prod 模式 api_base 必须使用 https"):
        validate_llm_api_base("http://api.deepseek.com/v1")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/v1",
        "http://169.254.169.254/latest",
        "http://10.0.0.5/v1",
    ],
)
def test_api_base_rejects_private_literal_addresses_in_dev(url, monkeypatch):
    """即使 APP_MODE 缺省为 dev，也不能把凭证发往内网 literal IP。"""
    from backend.api.admin.schemas import validate_llm_api_base

    monkeypatch.delenv("APP_MODE", raising=False)
    monkeypatch.delenv("LLM_ALLOWED_HOSTS", raising=False)

    with pytest.raises(ValueError, match="禁止 api_base 指向内网地址"):
        validate_llm_api_base(url)


@pytest.mark.asyncio(loop_scope="session")
async def test_build_llm_state_rejects_untrusted_runtime_api_base():
    """DB 中绕过 API 写入的 api_base 也必须在 provider 构造前复验。"""
    from backend.main import _build_llm_state

    settings = SimpleNamespace(encryption_key="test-encryption-key")
    config = {
        "api_base": "http://169.254.169.254/latest",
        "api_key": "encrypted-or-legacy-key",
        "model": "test-model",
    }

    with (
        patch(
            "backend.main.load_llm_config_from_db",
            new=AsyncMock(
                return_value=(
                    [
                        {
                            "id": "db-provider",
                            "type": "openai_compatible",
                            "config": config,
                        }
                    ],
                    {},
                )
            ),
        ),
        patch(
            "backend.main.decrypt_api_key",
            side_effect=ValueError("legacy plaintext"),
        ),
        patch(
            "backend.main.validate_llm_api_base",
            side_effect=ValueError("private address"),
        ) as validate_api_base,
        patch("backend.main.LLMRegistry.create") as create_provider,
    ):
        providers, routing, skipped, db_has_providers = await _build_llm_state(
            settings, MagicMock()
        )

    validate_api_base.assert_called_once_with(config["api_base"])
    create_provider.assert_not_called()
    assert providers == {}
    assert routing == {}
    assert skipped == ["db-provider"]
    assert db_has_providers is True


@pytest.mark.asyncio(loop_scope="session")
async def test_build_llm_state_distinguishes_all_disabled_db_providers():
    """DB 有 provider 但全部禁用时不得触发 YAML fallback。"""
    from backend.main import _build_llm_state

    settings = SimpleNamespace(encryption_key="test-encryption-key")
    with patch(
        "backend.main.load_llm_config_from_db",
        new=AsyncMock(return_value=([], {"generation": []})),
    ):
        providers, routing, skipped, db_has_providers = await _build_llm_state(
            settings, MagicMock()
        )

    assert providers == {}
    assert routing == {"generation": []}
    assert skipped == []
    assert db_has_providers is True


def test_lifespan_does_not_reference_undefined_db_config():
    """静态回归：lifespan 不得引用 _build_llm_state 内部的局部变量 db_config。

    C1 的根因是 db_config 从 lifespan 移进 _build_llm_state 后，lifespan
    残留引用 → NameError。运行时冒烟测试依赖外部服务，用源码检查作确定性兜底。
    """
    from backend.main import lifespan

    source = inspect.getsource(lifespan)
    assert "db_config" not in source, (
        "lifespan 引用了 db_config，该变量已移入 _build_llm_state 函数体，"
        "lifespan 作用域不存在 → 启动时 NameError（C1 回归）"
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_lifespan_starts_and_wires_llm_state():
    """运行时冒烟：lifespan 完整启动，app.state.llm/rag 非 None。

    mock weaviate + BGE（GPU/模型下载依赖），DB 连测试库（seed 幂等，
    不污染开发库）。lifespan 结束后恢复 app.state，避免污染后续测试。
    """
    import backend.main
    from backend.db.session import get_engine as real_get_engine

    test_dsn = os.environ.get("TEST_DATABASE_URL")
    if not test_dsn:
        pytest.skip("需 TEST_DATABASE_URL 才能跑 lifespan 运行时冒烟测试")

    mock_weaviate = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder._model_name = "test-emb"
    mock_embedder._device = "cpu"
    mock_embedder._dimension = 1024
    mock_embedder.embed.side_effect = lambda texts: [[0.0] * 1024 for _ in texts]
    mock_reranker = MagicMock()
    mock_reranker._model_name = "test-rerank"
    mock_reranker._device = "cpu"

    app = backend.main.app
    saved_state = dict(app.state.__dict__)

    try:
        with (
            patch.object(backend.main.weaviate, "connect_to_local", return_value=mock_weaviate),
            patch.object(backend.main, "BGEEmbedder", return_value=mock_embedder),
            patch.object(backend.main, "BGEReranker", return_value=mock_reranker),
            patch.object(
                backend.main, "get_engine", side_effect=lambda _: real_get_engine(test_dsn)
            ),
        ):
            async with backend.main.lifespan(app):
                assert app.state.llm is not None, "lifespan 未设置 app.state.llm"
                assert app.state.rag is not None, "lifespan 未设置 app.state.rag"
    finally:
        # 恢复 app.state（lifespan 创建的 engine 已在 lifespan.finally dispose）
        app.state.__dict__.clear()
        app.state.__dict__.update(saved_state)
