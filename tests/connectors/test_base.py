"""RawDocument 数据契约单元测试。

验证 P8 多分支能力新增的 ``branch`` 字段默认值与显式赋值行为。
"""

import pytest

from backend.connectors.base import RawDocument


@pytest.mark.unit
def test_raw_document_branch_default():
    """未显式传入 branch 时,默认应为空字符串(向后兼容)。"""

    doc = RawDocument(
        source_id="a/b/main/c.py",
        source_type="local_git",
        product="p",
        title="c",
        content="x",
        url="u",
        metadata={},
        content_hash="h",
    )
    assert doc.branch == ""


@pytest.mark.unit
def test_raw_document_branch_set():
    """显式传入 branch 时,应原样保留(如 hw-v1.2 分支)。"""

    doc = RawDocument(
        source_id="a/b/hw-v1.2/c.py",
        source_type="local_git",
        product="p",
        title="c",
        content="x",
        url="u",
        metadata={},
        content_hash="h",
        branch="hw-v1.2",
    )
    assert doc.branch == "hw-v1.2"
