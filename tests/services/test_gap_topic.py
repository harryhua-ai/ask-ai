"""Track F U-19 确定性主题短语派生 — 纯函数单元测试(RED→GREEN)。

冻结合同(track-f-contract U-19 / matrix-TI-12 / remediation plan §5 U-19):
- 确定性派生优先;LLM 仅当确定性质量明显不足且另行授权(本轨禁用 LLM);
- 主题必须稳定(同簇内容多次派生同值)且忠实于 cluster 内容;
- 无主题 → 回退代表问句(UI 路径;派生函数返回 None)。

派生规则冻结(backend/services/gap_topic.py):
- 语料 = representative_question + 去重后 sample_questions;去重后不足
  2 条不同问句 → None(单问句簇:代表问句即主题,无需派生);
- 拉丁/数字 token(长度 ≥2,大小写归一比较)取全语料交集;
- CJK 公共子串(长度 2..12)取全语料交集,仅保留极大子串;
- 纯疑问框架词候选(什么/怎么/是否/哪些/如何/吗…)剔除 —— 框架词不是内容;
- 片段按代表问句中的出现位置排序拼装(忠实原文语序,保留原文大小写);
- 全程零随机/零外部调用/零词表硬编码主题 —— 同输入恒同输出。
"""

import pytest

from backend.services.gap_topic import derive_gap_topic

pytestmark = [pytest.mark.unit]


class TestLatinCommonFactor:
    """拉丁/数字公共因子(参考 PNG 主题「NE101 PoE 支持信息缺失」的实体核)。"""

    def test_latin_tokens_common_across_all_questions(self):
        topic, derivation = derive_gap_topic(
            "NE101 是否支持 PoE",
            ["NE101 PoE 标准是什么", "NE101 PoE 最大功率是多少"],
        )
        # 全语料公共拉丁 token = {NE101, PoE};CJK 无公共子串
        assert derivation == "cross_question_common_factor"
        assert topic == "NE101 PoE"

    def test_latin_token_case_normalized_match_preserves_original_casing(self):
        topic, _ = derive_gap_topic(
            "POE 供电方案 NE101",
            ["ne101 poe 功率", "Ne101 PoE 标准"],
        )
        # 交集 {poe, ne101};按代表问句语序输出,保留代表问句原文大小写
        assert topic == "POE NE101"

    def test_number_token_common(self):
        topic, _ = derive_gap_topic(
            "SDK 1.2 版本 bug",
            ["SDK 1.2 装不上", "1.2 版本 SDK 崩溃"],
        )
        # token 化允许内部点分("1.2" 为完整 token);公共 = {sdk, 1.2}
        assert topic == "SDK 1.2"

    def test_no_common_latin_token(self):
        topic, derivation = derive_gap_topic("电池续航差", ["屏幕亮度低", "声音异常"])
        assert topic is None
        assert derivation is None


class TestCjkCommonFactor:
    """CJK 公共子串(共因子提取)。"""

    def test_cjk_common_substring_extracted(self):
        topic, derivation = derive_gap_topic(
            "NE101 支持哪些 PoE 标准",
            ["NE101 的 PoE 标准是什么"],
        )
        # 公共:拉丁 {NE101, PoE} + CJK 极大公共子串「标准」
        assert derivation == "cross_question_common_factor"
        assert topic == "NE101 PoE 标准"

    def test_frame_word_only_common_substring_dropped(self):
        # 公共 CJK 只有疑问框架词「什么」→ 非内容,不得成为主题
        topic, derivation = derive_gap_topic(
            "价格 什么 区间合理",
            ["颜色 什么 可选"],
        )
        assert topic is None
        assert derivation is None

    def test_frame_word_substring_inside_content_candidate_is_kept(self):
        # 「支持什么」含框架词但整体是内容候选(极大子串),框架词剔除仅作用于
        # 「整个候选就是框架词」的情形
        topic, _ = derive_gap_topic(
            "NE101 支持什么 PoE 模式",
            ["NE101 支持什么 供电方式"],
        )
        # 公共 CJK 极大子串 =「支持什么」;拉丁 = {NE101}
        assert topic == "NE101 支持什么"


class TestFaithfulness:
    """忠实性:主题片段必须逐字出现在语料每条问句中。"""

    def test_topic_pieces_are_literal_substrings_of_representative(self):
        topic, _ = derive_gap_topic(
            "安装步骤缺少截图",
            ["安装步骤 不完整", "安装步骤哪里看"],
        )
        assert topic == "安装步骤"
        # 忠实性:主题本身是代表问句的子串(逐字)
        assert topic in "安装步骤缺少截图"

    def test_no_common_content_returns_none(self):
        topic, derivation = derive_gap_topic(
            "如何配置 APN",
            ["屏幕总成多少钱", "质保几年"],
        )
        assert topic is None
        assert derivation is None


class TestStability:
    """稳定性:同输入多次派生恒同值(同簇跨请求稳定)。"""

    def test_repeated_calls_identical(self):
        r = "NE101 是否支持 PoE"
        s = ["NE101 PoE 标准是什么", "NE101 PoE 最大功率是多少"]
        results = {derive_gap_topic(r, s) for _ in range(50)}
        assert len(results) == 1

    def test_sample_order_does_not_change_topic(self):
        # 语料集合相同、样例顺序不同 → 同一主题(簇内容语义不变)
        a = derive_gap_topic("NE101 支持 PoE 吗", ["PoE 标准 NE101 版本", "NE101 PoE 功率"])
        b = derive_gap_topic("NE101 支持 PoE 吗", ["NE101 PoE 功率", "PoE 标准 NE101 版本"])
        assert a == b


class TestCorpusGuard:
    """语料守卫:去重后不足 2 条不同问句 → None(回退路径)。"""

    def test_single_question_cluster(self):
        assert derive_gap_topic("NE101 是否支持 PoE", []) == (None, None)
        assert derive_gap_topic("NE101 是否支持 PoE", None) == (None, None)

    def test_samples_duplicated_of_representative(self):
        assert derive_gap_topic("同一问题", ["同一问题", "同一问题"]) == (None, None)

    def test_empty_representative(self):
        assert derive_gap_topic("", ["有样例但代表问句为空"]) == (None, None)

    def test_none_representative(self):
        assert derive_gap_topic(None, ["x"]) == (None, None)  # type: ignore[arg-type]


class TestLengthGuard:
    """长度守卫:主题超长按片段边界截断(不截半词)。"""

    def test_long_topic_truncated_at_piece_boundary(self):
        r = "abcdefghij klmnopqrst uvwxyz 超长公共内容词一 超长公共内容词二"
        s = ["abcdefghij klmnopqrst uvwxyz 超长公共内容词一 超长公共内容词二 尾部",
             "abcdefghij klmnopqrst uvwxyz 超长公共内容词一 超长公共内容词二 其他"]
        topic, derivation = derive_gap_topic(r, s, max_len=30)
        assert derivation == "cross_question_common_factor"
        assert len(topic) <= 30
        # 截断发生在片段边界:保留的每个片段完整出现
        for piece in topic.split(" "):
            if piece:
                assert piece in r
