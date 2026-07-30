"""config_loader 测试。"""

from backend.services.config_loader import load_data_sources_from_yaml


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
