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
