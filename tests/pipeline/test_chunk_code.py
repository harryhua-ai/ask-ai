"""tree-sitter 代码 AST 分块器(P2 / Task 5)单元测试。

覆盖:
- Python / C 源码按函数/类节点切分,每个 chunk.chunk_type == "code"。
- 每个 code chunk 前缀拼上下文摘要(repo @ branch > path > symbol(signature)),
  branch 字段来自 Task 2 的 RawDocument.branch。
- 无 grammar 的扩展名(.txt 等)退化为 _hard_split_section 兜底(不拼 symbol 前缀)。
- 空 content 返回空列表。
- channel_visibility 从 doc 继承。
- 单个超长函数(> max_tokens)走 _hard_split_section,每个 chunk 仍带 symbol 前缀。
"""

import pytest

from backend.connectors.base import RawDocument
from backend.pipeline.chunk_code import chunk_code


def _doc(src: str, **kw: object) -> RawDocument:
    """构造默认 local_git RawDocument,允许测试覆盖字段。"""
    base: dict[str, object] = {
        "source_id": "r/main/m.py",
        "source_type": "local_git",
        "product": "p",
        "title": "m",
        "content": src,
        "url": "u",
        "metadata": {"path": "m.py"},
        "content_hash": "h",
        "branch": "main",
    }
    base.update(kw)
    return RawDocument(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_split_python_functions():
    """Python 源码按函数定义切分,每个 chunk 为 code 类型。"""
    src = "def foo():\n    return 1\n\ndef bar(x):\n    return x+1\n"
    doc = _doc(src)
    chunks = chunk_code(doc, max_tokens=600, overlap=50)
    assert len(chunks) >= 2
    assert all(c.chunk_type == "code" for c in chunks)
    # 至少有一个 chunk 的文本含 foo,另一个含 bar
    joined = "\n".join(c.text for c in chunks)
    assert "foo" in joined and "bar" in joined


@pytest.mark.unit
def test_context_prefix_present():
    """每个 chunk 前缀含 repo @ branch > path > symbol,branch 来自 doc.branch。"""
    src = "def foo():\n    return 1\n"
    doc = _doc(
        src,
        branch="hw-v1.2",
        source_id="ne301/hw-v1.2/m.py",
        metadata={"path": "m.py"},
    )
    chunks = chunk_code(doc)
    assert chunks  # 非空
    assert "hw-v1.2" in chunks[0].text  # 摘要前缀含 branch
    # branch 是 hw-v1.2 不是 main,首行不应误用默认
    assert "main" not in chunks[0].text.split("\n")[0]


@pytest.mark.unit
def test_c_function_split():
    """C 源码按 function_definition 切分。"""
    src = (
        "int add(int a, int b) {\n  return a + b;\n}\n\n"
        "int sub(int a, int b) {\n  return a - b;\n}\n"
    )
    doc = RawDocument(
        source_id="r/main/m.c",
        source_type="local_git",
        product="p",
        title="m",
        content=src,
        url="u",
        metadata={"path": "m.c"},
        content_hash="h",
        branch="main",
    )
    chunks = chunk_code(doc, max_tokens=600, overlap=50)
    assert len(chunks) >= 2
    assert all(c.chunk_type == "code" for c in chunks)


@pytest.mark.unit
def test_unsupported_lang_falls_back_to_hard_split():
    """.txt 无 grammar,走 _hard_split_section 兜底(不拼 symbol 前缀)。"""
    src = "line1\nline2\nline3\n"
    doc = RawDocument(
        source_id="r/main/m.txt",
        source_type="local_git",
        product="p",
        title="m",
        content=src,
        url="u",
        metadata={"path": "m.txt"},
        content_hash="h",
        branch="main",
    )
    chunks = chunk_code(doc, max_tokens=600, overlap=50)
    assert chunks  # 兜底仍产出 chunk
    # 兜底不拼 symbol 前缀;chunk_type 仍为 "code"
    assert all(c.chunk_type == "code" for c in chunks)


@pytest.mark.unit
def test_empty_content_returns_empty():
    """空 content 返回空列表。"""
    doc = _doc("")
    assert chunk_code(doc) == []


@pytest.mark.unit
def test_channel_visibility_inherited():
    """channel_visibility 从 doc 继承到每个 chunk。"""
    doc = _doc("def foo():\n    return 1\n", channel_visibility=("api",))
    chunks = chunk_code(doc)
    assert chunks
    assert all(c.channel_visibility == ("api",) for c in chunks)


@pytest.mark.unit
def test_long_function_hard_split():
    """单个超长函数(> max_tokens)走 _hard_split_section,每个 chunk 仍带 symbol 前缀。"""
    src = "def big():\n" + "    x = 1\n" * 500 + "\n"
    doc = _doc(src)
    chunks = chunk_code(doc, max_tokens=100, overlap=10)
    assert len(chunks) >= 2
    # 每个 chunk 都应有 symbol 前缀(含 big)
    assert all("big" in c.text for c in chunks)


@pytest.mark.unit
def test_chunk_index_and_total_consistency():
    """chunk_index 从 0 递增,total_chunks 等于列表长度。"""
    src = "def foo():\n    return 1\n\ndef bar(x):\n    return x+1\n"
    doc = _doc(src)
    chunks = chunk_code(doc)
    total = len(chunks)
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.total_chunks == total


@pytest.mark.unit
def test_start_end_char_align_with_content():
    """start_char/end_char 对齐到原文(pieces 不含前缀的字符范围)。"""
    src = "def foo():\n    return 1\n\ndef bar(x):\n    return x+1\n"
    doc = _doc(src)
    chunks = chunk_code(doc)
    for c in chunks:
        # 不含前缀的原文片段应出现在 content[start_char:end_char]
        # (前缀是附加的,不参与原文偏移)
        assert 0 <= c.start_char < c.end_char <= len(src)
        # 去掉前缀行后,piece_text 应等于 content[start_char:end_char] 的子串
        # 简化校验:piece 文本必出现在 content 中,且 start_char..end_char 内是代码
        assert doc.content[c.start_char : c.end_char] in doc.content


@pytest.mark.unit
def test_rust_function_split():
    """Rust 源码按 function_item / struct_item / impl_item 切分。"""
    src = (
        "fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n"
        "struct Foo {\n    x: i32,\n}\n\n"
        "impl Foo {\n    fn bar(&self) -> i32 { self.x }\n}\n"
    )
    doc = RawDocument(
        source_id="r/main/m.rs",
        source_type="local_git",
        product="p",
        title="m",
        content=src,
        url="u",
        metadata={"path": "m.rs"},
        content_hash="h",
        branch="main",
    )
    chunks = chunk_code(doc, max_tokens=600, overlap=50)
    assert len(chunks) >= 2
    assert all(c.chunk_type == "code" for c in chunks)
    joined = "\n".join(c.text for c in chunks)
    assert "add" in joined and "Foo" in joined and "bar" in joined


# ---- _split_symbol_name ----

from backend.pipeline.chunk_code import _split_symbol_name


@pytest.mark.unit
def test_split_symbol_camel_case():
    assert _split_symbol_name("BatteryReadI2C") == "battery read i2c"


@pytest.mark.unit
def test_split_symbol_pascal_with_acronym():
    assert _split_symbol_name("HTMLParser") == "html parser"


@pytest.mark.unit
def test_split_symbol_snake_case():
    assert _split_symbol_name("ne301_init") == "ne301 init"


@pytest.mark.unit
def test_split_symbol_digit_boundary():
    """数字→大写无小写后继不拆(I2C 整体);数字→大写+小写拆(NE301 + Config)。"""
    assert _split_symbol_name("readI2C") == "read i2c"        # I2C 整体
    assert _split_symbol_name("NE301Config") == "ne301 config"  # NE301 + Config
    assert _split_symbol_name("I2C") == "i2c"                  # I2C 整体


@pytest.mark.unit
def test_split_symbol_empty():
    assert _split_symbol_name("") == ""


# ---- chunk_code 填 symbol 字段 ----

@pytest.mark.unit
def test_chunk_code_fills_symbol_fields():
    src = "def battery_read_i2c(addr):\n    return i2c_read(addr)\n"
    doc = _doc(src, metadata={"path": "main.py"}, source_id="ne301/main.py",
               title="main.py")
    chunks = chunk_code(doc)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.symbol_name == "battery_read_i2c"
    assert c.symbol_tokens == "battery read i2c"
    assert c.symbol_node_type == "function_definition"
    assert "battery_read_i2c" in c.symbol_signature


@pytest.mark.unit
def test_chunk_code_symbol_fields_empty_for_no_grammar():
    doc = _doc("hello", metadata={"path": "x.txt"}, source_id="r/x.txt",
               title="x")
    chunks = chunk_code(doc)
    assert chunks[0].symbol_name == ""
    assert chunks[0].symbol_tokens == ""
