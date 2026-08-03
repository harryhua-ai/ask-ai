"""tree-sitter 代码 AST 分块器(P2 / Task 5)。

按函数/类/方法节点对源码做 AST 级切分,每个 code chunk 前缀拼上下文摘要
``// repo @ branch > path > symbol(signature)``,使下游检索能直接命中带语义
上下文的代码片段。无 grammar 的扩展名(如 .txt)退化为按
:func:`backend.pipeline.chunk._hard_split_section` 兜底(不拼 symbol 前缀)。

设计要点:
- 复用 :mod:`backend.pipeline.chunk` 的 ``Chunk`` / ``_estimate_tokens`` /
  ``_hard_split_section`` 避免重复实现 token 估算与滑窗硬切逻辑。
- tree-sitter 的 ``node.start_byte`` / ``node.end_byte`` 是 UTF-8 byte 偏移,
  而 ``Chunk.start_char`` / ``end_char`` 是 Python str 字符偏移。用
  :func:`_build_byte_to_char_map` 一次性构建全文 byte→char 映射,精确处理
  中文注释 / Unicode 字符串(对纯 ASCII 两者相等,转换零损耗)。
- symbol 提取:对目标节点做前序 DFS,取首个 identifier-like 节点(``identifier``
  / ``type_identifier`` / ``name`` / ``word``)作为符号名;signature 取节点首行
  文本(去尾部 ``{`` / ``:`` 等语法标记),最长 80 字符截断。
- 前缀不计入 ``max_tokens`` 预算:先对 section 原文做 ``_hard_split_section``,
  再给每个 piece 拼前缀——保证 symbol 摘要完整,不因 token 上限被截断。
- ``channel_visibility`` 从 ``doc`` 继承,与 :func:`chunk_document` 行为一致。
"""

import logging
import re

from backend.connectors.base import RawDocument
from backend.pipeline.chunk import (
    Chunk,
    _build_byte_to_char_map,
    _hard_split_section,
)

logger = logging.getLogger(__name__)

# 文件扩展名 -> tree-sitter 语言名(无后缀的点号已补全)。
LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".sh": "bash",
    ".bash": "bash",
}

# 各语言捕获的顶层节点类型名(tree-sitter 节点 type 字符串)。
# 切到目标节点后不再向其内部递归(避免 class 内 method 被重复切)。
FUNCTION_NODE_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset({"function_definition", "class_definition"}),
    "c": frozenset({"function_definition", "class_specifier", "struct_specifier"}),
    "cpp": frozenset({"function_definition", "class_specifier", "struct_specifier"}),
    "rust": frozenset({"function_item", "struct_item", "impl_item", "enum_item", "trait_item"}),
    "typescript": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "function_expression",
        }
    ),
    "tsx": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "function_expression",
        }
    ),
    "javascript": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "function_expression",
        }
    ),
    "bash": frozenset({"function_definition"}),
}

# identifier-like 节点类型:不同语言用不同节点名承载符号标识。
_NAME_NODE_TYPES: frozenset[str] = frozenset({"identifier", "type_identifier", "name", "word"})

# signature 中需去除的尾部语法标记(按优先级 rstrip)。
_SIG_STRIP_CHARS = "{}: \t\r\n"

# signature 最大长度(字符)。
_MAX_SIG_LEN = 80

# camelCase / PascalCase / 数字边界拆分规则:
#   小写→大写:camelCase 边界(readI2C → read + I2C)
#   大写→大写+小写:缩写词边界(HTMLParser → HTML + Parser)
#   数字→大写+小写:NE301 + Config(数字后接新词)
#   数字→大写无小写:I2C 整体(不拆,2→C 后无小写)
_CAMEL_BOUNDARY = re.compile(
    r"(?<=[a-z])(?=[A-Z])"        # 小写→大写
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # 大写→大写+小写
    r"|(?<=[0-9])(?=[A-Z][a-z])"  # 数字→大写+小写
)


def _split_symbol_name(name: str) -> str:
    """camelCase / PascalCase / snake_case → 空格小写;缩写词(I2C / NE301)整体保留。

    用于派生 ``symbol_tokens``,让 BM25 对原始 query 中的标识符命中 camelCase
    符号(如 query "I2C" 命中 ``BatteryReadI2C`` → tokens 含 "i2c")。

    Args:
        name: 原始符号名(如 ``BatteryReadI2C`` / ``ne301_init``)。

    Returns:
        空格分隔的小写 token 串;空输入返回空串。
    """
    if not name:
        return ""
    s = name.replace("_", " ")
    s = _CAMEL_BOUNDARY.sub(" ", s)
    return " ".join(tok.lower() for tok in s.split() if tok)

# camelCase / PascalCase / 数字边界拆分规则:
#   小写→大写:camelCase 边界(readI2C → read + I2C)
#   大写→大写+小写:缩写词边界(HTMLParser → HTML + Parser)
#   数字→大写+小写:NE301 + Config(数字后接新词)
#   数字→大写无小写:I2C 整体(不拆,2→C 后无小写)
_CAMEL_BOUNDARY = re.compile(
    r"(?<=[a-z])(?=[A-Z])"        # 小写→大写
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # 大写→大写+小写
    r"|(?<=[0-9])(?=[A-Z][a-z])"  # 数字→大写+小写
)


def _split_symbol_name(name: str) -> str:
    """camelCase / PascalCase / snake_case → 空格小写;缩写词(I2C / NE301)整体保留。

    用于派生 ``symbol_tokens``,让 BM25 对原始 query 中的标识符命中 camelCase
    符号(如 query "I2C" 命中 ``BatteryReadI2C`` → tokens 含 "i2c")。

    Args:
        name: 原始符号名(如 ``BatteryReadI2C`` / ``ne301_init``)。

    Returns:
        空格分隔的小写 token 串;空输入返回空串。
    """
    if not name:
        return ""
    s = name.replace("_", " ")
    s = _CAMEL_BOUNDARY.sub(" ", s)
    return " ".join(tok.lower() for tok in s.split() if tok)


def _build_byte_to_char_map_local(encoded: bytes) -> list[int]:
    """构建 byte 偏移 -> char 偏移映射表(委托到 chunk._build_byte_to_char_map)。

    保留薄封装以稳定导入边界;真正实现在 :mod:`backend.pipeline.chunk`,
    保证与 ``_hard_split_section`` 的 byte→char 语义一致。
    """
    return _build_byte_to_char_map(encoded)


def _byte_to_char_offset(byte_to_char: list[int], byte_offset: int) -> int:
    """UTF-8 byte 偏移 -> Python str 字符偏移(用预构建映射表,O(1))。

    Args:
        byte_to_char: :func:`_build_byte_to_char_map` 的输出。
        byte_offset: UTF-8 byte 偏移(必须在 ``[0, len(encoded)]`` 范围内)。

    Returns:
        对应的字符偏移(位于多字节字符内部时取该字符起始偏移,与
        ``len(encoded[:b].decode("utf-8", errors="ignore"))`` 等价)。
    """
    if byte_offset < 0:
        return 0
    if byte_offset >= len(byte_to_char):
        return byte_to_char[-1]
    return byte_to_char[byte_offset]


def _find_symbol_name(node) -> str:
    """对 AST 节点做前序 DFS,取首个 identifier-like 节点的文本。

    覆盖:
    - Python / TS / TSX / JS:function_declaration / class_declaration 的
      直接子 ``identifier``。
    - C / CPP:function_declarator 内嵌的 ``identifier``。
    - Rust:struct_item / impl_item 的 ``type_identifier``、function_item 的
      ``identifier``。
    - Bash:function_definition 的首 ``word``。

    Args:
        node: tree-sitter Node。

    Returns:
        符号名(解码后的 str);找不到返回空串。
    """
    if node.type in _NAME_NODE_TYPES:
        try:
            return node.text.decode("utf-8", errors="ignore")
        except AttributeError:  # pragma: no cover - 防御性(node.text 可能为 None)
            return ""
    for child in node.children:
        name = _find_symbol_name(child)
        if name:
            return name
    return ""


def _extract_signature(node) -> str:
    """从 AST 节点提取 signature 文本(节点首行,去尾部 ``{`` / ``:``)。

    Args:
        node: tree-sitter Node(目标函数/类节点)。

    Returns:
        signature 字符串(最长 80 字符);无法提取返回空串。
    """
    try:
        raw = node.text.decode("utf-8", errors="ignore")
    except AttributeError:  # pragma: no cover - 防御性(node.text 可能为 None)
        return ""
    if not raw:
        return ""
    first_line = raw.split("\n", 1)[0]
    sig = first_line.rstrip(_SIG_STRIP_CHARS)
    return sig[:_MAX_SIG_LEN]


def _comment_marker(path: str) -> str:
    """根据文件扩展名选择注释前缀符(C 系 / Rust 用 //,Python / Bash 等用 #)。"""
    return "//" if path.endswith((".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".rs")) else "#"


def _symbol_prefix(doc: RawDocument, path: str, symbol: str, signature: str) -> str:
    """构造 chunk 前缀摘要 ``<cmt> repo @ branch > path > symbol(signature)``。

    Args:
        doc: 所属 RawDocument(取 source_id / branch)。
        path: 文件路径(取自 metadata["path"])。
        symbol: 符号名(函数/类/方法名)。
        signature: signature 文本(去尾部语法标记)。

    Returns:
        单行注释前缀 + 换行;symbol 与 signature 均空时返回空串
        (调用方据此决定是否拼接)。
    """
    if not symbol:
        return ""
    cmt = _comment_marker(path)
    sym = f"{symbol}({signature})" if signature else symbol
    # repo 取 source_id 首段(source_id 形如 "<repo>/<branch>/<path>")。
    repo = doc.source_id.split("/")[0] if "/" in doc.source_id else doc.source_id
    branch = doc.branch or ""
    return f"{cmt} {repo} @ {branch} > {path} > {sym}\n"


def _extract_path(doc: RawDocument) -> str:
    """从 doc.metadata 取 path(缺失返回空串)。"""
    path = doc.metadata.get("path", "")
    return path if isinstance(path, str) else ""


def _resolve_extension(path: str) -> str:
    """从路径解析小写扩展名(含点号);无扩展名返回空串。"""
    if "." not in path:
        return ""
    return ("." + path.rsplit(".", 1)[-1]).lower()


def _collect_sections(
    content: str,
    lang: str,
    byte_to_char: list[int],
) -> list[tuple[str, int, int, str, str, str]]:
    """解析 AST,收集顶层函数/类/方法节点对应的 section。

    遇到目标节点即记录并停止向其内部递归(避免 class 内 method 被重复切);
    目标节点之间的非函数顶层文本(imports / 全局变量 / 注释)被丢弃——
    代码检索场景下,符号级 chunk 比全文 chunk 更有意义。

    Args:
        content: 原文(用于按 char 偏移切 section 文本)。
        lang: tree-sitter 语言名。
        byte_to_char: 全文 byte→char 映射表。

    Returns:
        列表,每项 ``(section_text, start_char, end_char, symbol, signature,
        node_type)``。无目标节点时返回空列表(调用方决定是否退化为整体 section)。
    """
    from tree_sitter_language_pack import get_parser

    parser = get_parser(lang)
    tree = parser.parse(content.encode("utf-8"))
    target_types = FUNCTION_NODE_TYPES[lang]

    sections: list[tuple[str, int, int, str, str, str]] = []

    def walk(node) -> None:
        if node.type in target_types:
            start_c = _byte_to_char_offset(byte_to_char, node.start_byte)
            end_c = _byte_to_char_offset(byte_to_char, node.end_byte)
            text = content[start_c:end_c]
            symbol = _find_symbol_name(node)
            signature = _extract_signature(node)
            sections.append((text, start_c, end_c, symbol, signature, node.type))
            # 不再向函数/类体内递归,避免方法被重复切
            return
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return sections


def _build_chunks(
    doc: RawDocument,
    pieces: list[tuple[str, int, int, str, str, str]],
) -> list[Chunk]:
    """构造不可变 Chunk 列表(每个 piece 拼 symbol 前缀 + 填 symbol 元数据)。

    Args:
        doc: 所属 RawDocument。
        pieces: 列表,每项
            ``(piece_text, start_char, end_char, symbol, signature, node_type)``。
            start_char/end_char 是 piece_text 在 doc.content 中的字符偏移
            (不含前缀);symbol/signature/node_type 用于拼前缀与填充 Chunk 的
            symbol_* 字段(symbol 空则不拼前缀)。

    Returns:
        Chunk 列表,chunk_index 从 0 递增,total_chunks 等于列表长度;
        chunk_type 固定 ``"code"``,channel_visibility 从 doc 继承,
        symbol_tokens 由 symbol_name 经 camelCase 拆分派生。
    """
    total = len(pieces)
    path = _extract_path(doc)
    channel_vis = getattr(doc, "channel_visibility", ("widget", "api"))
    chunks: list[Chunk] = []
    for i, (text, start, end, symbol, signature, node_type) in enumerate(pieces):
        prefix = _symbol_prefix(doc, path, symbol, signature)
        chunks.append(
            Chunk(
                text=prefix + text,
                document=doc,
                chunk_index=i,
                total_chunks=total,
                start_char=start,
                end_char=end,
                chunk_type="code",
                doc_section="",
                channel_visibility=channel_vis,
                symbol_name=symbol,
                symbol_signature=signature,
                symbol_node_type=node_type,
                symbol_tokens=_split_symbol_name(symbol),
            )
        )
    return chunks


def chunk_code(
    doc: RawDocument,
    max_tokens: int = 600,
    overlap: int = 50,
) -> list[Chunk]:
    """按函数/类/方法 AST 节点切分源码文档。

    流程:
        1. 空 content 返回 [](见 Returns 段)。
        2. 取 ``metadata["path"]`` 扩展名 -> tree-sitter 语言名;无 grammar
           走 :func:`_hard_split_section` 兜底(不拼 symbol 前缀)。
        3. 全文构建 byte→char 映射,解析 AST,收集顶层函数/类/方法节点
           (遇目标节点停止向体内递归,避免方法被重复切)。
        4. 无目标节点时,整体作为一个 section(symbol 空 -> 不拼前缀)。
        5. 每个 section 走 ``_hard_split_section``(超长才切,否则原样返回),
           每个 piece 拼对应 symbol 前缀(前缀不计入 max_tokens,保证 symbol
           摘要完整)。
        6. 构造不可变 Chunk(chunk_type="code",channel_visibility 从 doc 继承)。

    Args:
        doc: 源码 RawDocument(``metadata["path"]`` 指示语言,``branch`` 进前缀)。
        max_tokens: 单 chunk 的 token 上限(默认 600)。
        overlap: 硬切时相邻 chunk 重叠的 token 数(默认 50)。

    Returns:
        Chunk 列表,顺序按 AST 出现次序;空 content 返回空列表。
    """
    content = doc.content
    if not content:
        return []

    encoded = content.encode("utf-8")
    byte_to_char = _build_byte_to_char_map_local(encoded)

    path = _extract_path(doc)
    ext = _resolve_extension(path)
    lang = LANG_MAP.get(ext)

    if lang is None:
        # 无 grammar:走 _hard_split_section 兜底,不拼 symbol 前缀
        hard = _hard_split_section(content, max_tokens, overlap)
        pieces = [(text, start, end, "", "", "") for text, start, end in hard if text]
        return _build_chunks(doc, pieces)

    # 2. tree-sitter 解析,收集函数/类/方法 section
    sections = _collect_sections(content, lang, byte_to_char)
    if not sections:
        # 无目标节点:整体作为单 section(symbol 空 -> 不拼前缀)
        sections = [(content, 0, len(content), "", "", "")]

    # 3. 每个 section 走 _hard_split_section,累加 section 全局偏移
    pieces: list[tuple[str, int, int, str, str, str]] = []
    for sec_text, sec_start_c, _sec_end_c, symbol, signature, node_type in sections:
        hard = _hard_split_section(sec_text, max_tokens, overlap)
        for text, rel_s, rel_e in hard:
            if not text:
                continue
            pieces.append((text, sec_start_c + rel_s, sec_start_c + rel_e,
                          symbol, signature, node_type))

    return _build_chunks(doc, pieces)


__all__: list[str] = [
    "FUNCTION_NODE_TYPES",
    "LANG_MAP",
    "chunk_code",
]
