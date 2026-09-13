"""确定性主题短语派生(U-19 / TI-12 / GAP-B2-6)—— Track F 专属服务。

**冻结合同**(track-f-contract.md U-19 / matrix-TI TI-12「冻结决定」列 /
remediation plan §5 U-19):

- **确定性派生优先**:从 cluster 代表问句 + 样例问句(既有持久化真相,
  question_clusters 表)稳定派生;LLM 仅当确定性质量明显不足且**另行授权**
  才可用 —— 本实现零 LLM、零随机、零外部调用、零主题词表硬编码;
- **稳定**:纯函数,同簇内容多次派生恒同值(同簇跨请求稳定);
- **忠实**:主题的每个片段逐字出现在语料(代表问句 + 全部去重样例)的
  每一条问句中 —— 跨问句公共因子,不是任何模型/词表的生成物;
- **回退**:不可派生(单问句簇 / 无公共内容因子 / 输入退化)→ ``None``,
  UI 回退代表问句(合同:无主题回退代表问句)。

**派生规则(冻结稿,随交付)**:

1. 语料 = [代表问句] + 去重样例问句(与代表问句相同的样例去重);
   去重后不同问句 < 2 → None(单问句簇:代表问句即主题,无需派生)。
2. 拉丁/数字 token:正则 ``[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*``,长度 ≥ 2,
   小写归一比较;取**全语料交集**;输出保留代表问句中的原文大小写。
3. CJK 公共子串:每条问句的极大 CJK 连续段(≥2 字)切出长度 2..12 的全部
   子串,取**全语料交集**;仅保留极大子串(不被其他保留项包含);
   整个候选恰为纯疑问框架词(什么/怎么/是否/哪些/如何/吗…)→ 剔除
   (框架词不是内容;含内容词的候选如「支持什么」保留)。
4. 片段按其在**代表问句中的出现位置**排序拼装(忠实原文语序);
   相邻片段均为 CJK 时直接连接,其余以单空格连接。
5. 长度守卫:超过 ``max_len``(默认 40)时自尾部按**片段边界**丢弃
   (不截半词);结果 < 2 字符 → None。

隐私:仅消费问题文本(操作者可见权威投影字段),零身份/零会话内容。
"""

import re

# 纯疑问框架词:仅当**整个 CJK 候选**由框架词构成时剔除(非内容词)。
# 注意:这是算法降噪规则,不是主题词表 —— 主题片段本身永远派生自 cluster 内容。
_FRAME_WORDS = (
    "是否",
    "什么",
    "怎么",
    "怎样",
    "如何",
    "为什么",
    "为啥",
    "哪些",
    "多少",
    "几个",
    "请问",
    "有没有",
    "能不能",
    "可不可以",
    "为什么呀",
    "吗",
    "呢",
    "吧",
    "么",
)

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")

_CJK_SUB_MIN = 2
_CJK_SUB_MAX = 12

DERIVATION_COMMON_FACTOR = "cross_question_common_factor"


def _is_pure_frame(candidate: str) -> bool:
    """整个候选剔除框架词后无剩余 → 纯框架词(非内容)。"""
    remainder = candidate
    for w in _FRAME_WORDS:
        remainder = remainder.replace(w, "")
    return remainder == ""


def _latin_tokens(text: str) -> list[str]:
    return _LATIN_TOKEN_RE.findall(text or "")


def _cjk_runs(text: str) -> list[str]:
    return _CJK_RUN_RE.findall(text or "")


def _cjk_substrings(run: str) -> set[str]:
    n = len(run)
    return {
        run[i : i + size]
        for size in range(_CJK_SUB_MIN, min(_CJK_SUB_MAX, n) + 1)
        for i in range(n - size + 1)
    }


def derive_gap_topic(
    representative_question: str | None,
    sample_questions: list[str] | None,
    max_len: int = 40,
) -> tuple[str | None, str | None]:
    """从 cluster 内容确定性派生主题短语。

    Args:
        representative_question: 聚类代表问句(question_clusters 权威字段)。
        sample_questions: 样例问句列表(question_clusters 权威字段)。
        max_len: 主题最大长度(按片段边界截断)。

    Returns:
        ``(topic, derivation)`` 二元组;不可派生时 ``(None, None)``。
        derivation = ``"cross_question_common_factor"``(冻结规则 ID)。
    """
    rq = (representative_question or "").strip()
    if not rq:
        return None, None

    # 1) 语料:代表问句 + 去重样例;去重后不足 2 条不同问句 → 不派生
    corpus: list[str] = [rq]
    for s in sample_questions or []:
        t = (s or "").strip()
        if t and t not in corpus:
            corpus.append(t)
    if len(corpus) < 2:
        return None, None

    # 2) 拉丁/数字 token 全语料交集(小写归一比较)
    common_latin_lower: set[str] | None = None
    for q in corpus:
        toks = {t.lower() for t in _latin_tokens(q) if len(t) >= 2}
        common_latin_lower = toks if common_latin_lower is None else (common_latin_lower & toks)
        if not common_latin_lower:
            break
    common_latin_lower = common_latin_lower or set()

    # 3) CJK 公共子串全语料交集 → 极大子串 → 剔除纯框架词
    common_cjk: set[str] | None = None
    for q in corpus:
        subs: set[str] = set()
        for run in _cjk_runs(q):
            subs |= _cjk_substrings(run)
        common_cjk = subs if common_cjk is None else (common_cjk & subs)
        if not common_cjk:
            break
    cjk_candidates: list[str] = []
    if common_cjk:
        kept = [c for c in common_cjk if not _is_pure_frame(c)]
        # 仅保留极大子串(不被另一保留项包含);同长同位歧义按字典序收敛
        kept = sorted(set(kept), key=lambda c: (-len(c), c))
        maximal: list[str] = []
        for c in kept:
            if not any(c in m for m in maximal):
                maximal.append(c)
        cjk_candidates = maximal

    if not common_latin_lower and not cjk_candidates:
        return None, None

    # 4) 片段按代表问句中的出现位置排序;保留代表问句原文大小写
    pieces: list[tuple[int, str, bool]] = []  # (position, piece, is_cjk)
    for m in _LATIN_TOKEN_RE.finditer(rq):
        if m.group(0).lower() in common_latin_lower:
            pieces.append((m.start(), m.group(0), False))
    for c in cjk_candidates:
        pos = rq.find(c)
        if pos >= 0:
            pieces.append((pos, c, True))
    if not pieces:
        return None, None
    pieces.sort(key=lambda p: (p[0], p[1]))

    def _assemble(selected: list[tuple[int, str, bool]]) -> str:
        out = ""
        for i, (_, piece, is_cjk) in enumerate(selected):
            if i == 0:
                out = piece
                continue
            prev_cjk = selected[i - 1][2]
            out += piece if (is_cjk and prev_cjk) else f" {piece}"
        return out

    # 5) 长度守卫:自尾部按片段边界丢弃,不截半词
    while pieces:
        topic = _assemble(pieces)
        if len(topic) <= max_len:
            if len(topic) < 2:
                return None, None
            return topic, DERIVATION_COMMON_FACTOR
        pieces = pieces[:-1]

    return None, None
