"""config_loader 测试。"""

import pytest

from backend.services.config_loader import _normalize_chain_item, load_data_sources_from_yaml


def test_load_data_sources_from_yaml():
    yaml_data = {
        "sources": [
            {"id": "test", "type": "github", "product": "test", "config": {"owner": "o"}},
        ]
    }
    sources = load_data_sources_from_yaml(yaml_data)
    assert len(sources) == 1
    assert sources[0]["id"] == "test"
    assert sources[0]["sync_interval"] == "24h"


@pytest.mark.parametrize(
    "item, expected",
    [
        # 旧字符串格式 → 对象，model 为 None
        ("deepseek", {"provider": "deepseek", "model": None}),
        # 新对象格式（有 model）
        ({"provider": "deepseek", "model": "v4-pro"}, {"provider": "deepseek", "model": "v4-pro"}),
        # 新对象格式（model 为 None = 用默认）
        ({"provider": "openrouter", "model": None}, {"provider": "openrouter", "model": None}),
        # 对象缺 model key → 补 None
        ({"provider": "moonshot"}, {"provider": "moonshot", "model": None}),
    ],
)
def test_normalize_chain_item(item, expected):
    """chain 元素归一化为 {provider, model} 对象（旧字符串兼容）。"""
    assert _normalize_chain_item(item) == expected
