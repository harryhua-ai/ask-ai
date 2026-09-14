"""v1.6.3 Track C(U-7 逐文档 content_type):内容类型词表与结构化推导。

冻结语义(track-c-contract U-7 / DS-P2-16/20):
- **结构化后端真值,connector/ingestion 写入链所有**;
- **前端禁止从文件名/文本推断**(前端只做词表→运营词的呈现映射);
- 词表冻结三值 + 未知兜底:

    product   商品(源系统结构化类型为商品/产品对象,如 WooCommerce products)
    page      页面(源系统结构化类型为网页/页面对象,如 HTML 站点页)
    document  文档(源系统结构化类型为文档文件,如 markdown/pdf/代码文件)

- NULL/空 = 不可用(unavailable,存量行诚实呈现,绝不推断回填)。

推导只消费连接器已知的**结构化事实**(源系统对象类型 / URL 后缀 /
MIME),不做内容文本语义判断。
"""

from __future__ import annotations

from typing import Any

CONTENT_TYPE_PRODUCT = "product"
CONTENT_TYPE_PAGE = "page"
CONTENT_TYPE_DOCUMENT = "document"

CONTENT_TYPES = (CONTENT_TYPE_PRODUCT, CONTENT_TYPE_PAGE, CONTENT_TYPE_DOCUMENT)

# 文档类文件后缀(结构化事实:文件扩展名 → document)。其余可读文本文件
# (markdown/代码配置等)同样归 document;纯网页面归 page。
_DOCUMENT_EXTS = frozenset(
    {
        ".md",
        ".markdown",
        ".rst",
        ".txt",
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".csv",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".sh",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".xml",
        ".sql",
        ".proto",
        ".ini",
        ".conf",
    }
)
_PAGE_EXTS = frozenset({".html", ".htm"})


def derive_content_type(source_type: str, url: str, metadata: dict[str, Any] | None) -> str:
    """按源类型结构化事实推导逐文档 content_type(后端权威;空串=不可用)。

    规则(全部结构化,零文本语义推断):
    - woocommerce:源仅暴露商品对象(WooCommerce products API)→ product;
    - web_crawl:URL 路径后缀 .pdf/文档类 → document;.html/htm/无后缀页面
      → page;其余文档类后缀 → document;
    - filesystem/github/local_git/db:仓库/目录文件(源系统对象=文件)
      → document;
    - 未知源类型:按 URL 后缀兜底(文档类→document,页面类→page);
      无结构化信号 → ""(调用方存 NULL,诚实不可用)。
    """
    meta = metadata or {}
    st = (source_type or "").strip().lower()
    if st == "woocommerce":
        # WooCommerce connector 只灌 products API 对象;结构化类型字段兜底核验
        obj_type = str(meta.get("type") or "").strip().lower()
        if obj_type and obj_type not in {"simple", "variable", "grouped", "external"}:
            return ""
        return CONTENT_TYPE_PRODUCT
    if st in {"web_crawl", "website"}:
        return _derive_from_url(url, default=CONTENT_TYPE_PAGE)
    if st in {"filesystem", "github", "local_git", "git"}:
        return _derive_from_url(url, default=CONTENT_TYPE_DOCUMENT)
    return _derive_from_url(url, default="")


def _derive_from_url(url: str, *, default: str) -> str:
    """URL 路径后缀 → 内容类型(结构化信号;无后缀用 default)。"""
    path = (url or "").split("?", 1)[0].split("#", 1)[0]
    ext = ""
    name = path.rsplit("/", 1)[-1]
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1].lower()
    if not ext:
        return default
    if ext in _PAGE_EXTS:
        return CONTENT_TYPE_PAGE
    if ext in _DOCUMENT_EXTS:
        return CONTENT_TYPE_DOCUMENT
    return default


def derive_web_content_type(url: str) -> str:
    """网页源(web_crawl)URL 后缀 → 内容类型;无结构化信号 → page。"""
    return _derive_from_url(url, default=CONTENT_TYPE_PAGE) or CONTENT_TYPE_PAGE
