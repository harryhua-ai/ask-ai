"""符号召回 e2e 验收(需全量索引,默认 skip)。

验证开发者代码层问题命中精确函数 symbol,而非整文件。

前置:
- Weaviate 已索引 ne301 代码(含 ``battery_read_i2c`` 类符号)。
- symbol_* property 已通过 ``scripts/migrate_add_symbol_props.py`` 增量加入,
  且代码 chunk 已重索引回填 symbol_* 值。

触发方式:
    设置环境变量 ``RUN_SYMBOL_E2E=1`` 运行本模块:
    ``RUN_SYMBOL_E2E=1 pytest tests/e2e/test_symbol_recall.py -v``

默认 skip,避免在无索引 / 无 Weaviate 的环境误跑。
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SYMBOL_E2E") != "1",
    reason="需全量索引 + symbol_* 回填,设 RUN_SYMBOL_E2E=1 触发",
)


@pytest.mark.e2e
def test_developer_question_hits_function():
    """开发者问题(NE301 I2C 读电池监控)命中精确函数,非整文件。

    索引 ne301 代码(含 battery_read_i2c),问 "NE301 怎么用 I2C 读电池监控寄存器",
    断言:rerank top 结果含 symbol_name == battery_read_i2c(或 i2c_read 类)。

    Note: 实现需真实 Weaviate + embedder + reranker。占位验收,待全量索引
    回填 symbol_* 后由用户触发。
    """
    # TODO: 接入真实 RAGOrchestrator / HybridSearcher,对 ne301 代码 corpus
    # 跑 "NE301 怎么用 I2C 读电池监控寄存器",断言 top 结果 symbol_name 非空
    # 且属于 i2c/battery 相关函数。
    pytest.skip("待全量索引回填 symbol_* 后实现(占位验收)")


@pytest.mark.e2e
def test_non_code_query_not_disturbed_by_symbol_recall():
    """非代码 query(产品 / 文档问题)召回不退步:符号召回天然低分,RRF 不抬高。

    Note: 需对比 20 问回归基线。占位,待全量索引后由用户触发批量回归。
    """
    pytest.skip("待 20 问回归基线脚本接入(占位验收)")