"""pytest 全局 fixtures。"""

from pathlib import Path

import pytest


@pytest.fixture
def config_dir() -> Path:
    """返回项目 config 目录路径。"""
    return Path(__file__).parent.parent / "config"
