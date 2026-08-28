"""ExclusionPolicy 极保守排除规则模块测试。"""

import pytest

from backend.connectors.exclusion import ExclusionPolicy


@pytest.mark.unit
def test_exclude_build_dirs():
    p = ExclusionPolicy({})
    assert p.should_exclude("build/main.c", 100)
    assert p.should_exclude("lib/node_modules/x.js", 100)


@pytest.mark.unit
def test_keep_cmsis_big_file():
    p = ExclusionPolicy({})
    # 源码保留,即使体积很大
    assert not p.should_exclude("Drivers/CMSIS/DSP/arm_common_tables.c", 5_000_000)


@pytest.mark.unit
def test_exclude_wave_test_data():
    p = ExclusionPolicy({})
    assert p.should_exclude("test/wave_1ch_16bits.c", 1_000_000)


@pytest.mark.unit
def test_exclude_binary_ext():
    p = ExclusionPolicy({})
    assert p.should_exclude("img/logo.png", 5000)


@pytest.mark.unit
def test_custom_exclude_regex():
    p = ExclusionPolicy({"exclude_regex": r"_test\.c$", "exclude_dirs": ["vendor/"]})
    assert p.should_exclude("src/foo_test.c", 100)
    assert not p.should_exclude("src/main.c", 100)


@pytest.mark.unit
def test_max_file_size_only_nonsource():
    p = ExclusionPolicy({"max_file_size": 1_000_000})
    assert not p.should_exclude("src/huge.c", 5_000_000)  # 源码不受限
    assert p.should_exclude("data/huge.json", 5_000_000)  # 非源码受限


def test_exclude_appledouble_metadata_files():
    """macOS ._* 元数据文件(任意层级)应被排除——2026-08 垃圾灌库事故防线。"""
    p = ExclusionPolicy({})
    # 根层级与任意子层级
    assert p.should_exclude("._NE101-PIR传感器功能咨询.md", 100)
    assert p.should_exclude("main/2026-05/._Dave-reply.md", 100)
    assert p.should_exclude("docs/i18n/en/._guide.mdx", 100)
    # 正常文件不受影响(含下划线/点开头的合法名)
    assert not p.should_exclude("main/_category_.json", 100)
    assert not p.should_exclude("main/docs/guide.md", 100)
