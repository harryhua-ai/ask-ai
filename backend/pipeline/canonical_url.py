"""Wiki citation URL 映射(CIT-URL Contract)。

Wiki 文档的 Docusaurus ``slug`` 是唯一允许生成 Wiki canonical route 的
authority。GitHub blob URL 是 ingestion/provenance 的权威 fallback；存量
Weaviate object 缺少 ``frontmatter_slug`` 时，不能从目录名猜 Wiki route，
否则改名/重排目录会把 citation 变成 broken 或软 404。

规则:

- 仅匹配 ``github.com/camthink-ai/wiki-documents/blob/<branch>/<path>``
  的 ``.md`` 文档；普通 GitHub、Website、WooCommerce 和其他 URL 原样返回。
- 有效的绝对 frontmatter slug 才映射到 ``wiki.camthink.ai/docs``。
- slug 缺失、为空、类型错误或格式不安全时，原样返回 GitHub blob URL，
  不启用历史路径猜测。
- 结构不适用或原始 URL 为空时，原样返回输入；展示层另行禁止空 URL
  进入可点击 sources。
"""

import ast
import re

# wiki 站点与源仓库(产品拍板的唯一映射目标;如换仓/换域,改这两个常量)
WIKI_BASE_URL = "https://wiki.camthink.ai"
WIKI_REPO = "camthink-ai/wiki-documents"

# github blob URL:严格匹配 owner/repo/blob/branch/path 四段结构
_GITHUB_BLOB_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/blob/[^/]+/(?P<path>.+)$")
_MD_SUFFIX = ".md"
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<body>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
_SLUG_LINE_RE = re.compile(r"(?m)^[ \t]*slug[ \t]*:[ \t]*(?P<value>.*?)\s*$")


def extract_frontmatter_slug(content: str) -> str | None:
    """读取 Docusaurus frontmatter 的 slug；缺少 key 与空/非法值可区分。"""
    match = _FRONTMATTER_RE.match(content or "")
    if match is None:
        return None
    slug_match = _SLUG_LINE_RE.search(match.group("body"))
    if slug_match is None:
        return None
    raw = slug_match.group("value").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        try:
            value = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return raw
        return value if isinstance(value, str) else raw
    return raw


def _canonical_url_from_slug(slug: object) -> str | None:
    """将 docs plugin 的绝对 slug 安全地挂到站点 ``/docs`` base route。"""
    if not isinstance(slug, str):
        return None
    value = slug.strip()
    if not value or not value.startswith("/"):
        return None
    if any(token in value for token in ("?", "#", "\\", "//")):
        return None
    if any(ord(char) < 32 or char.isspace() for char in value):
        return None
    parts = [part for part in value.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return None
    if not parts:
        return None
    return f"{WIKI_BASE_URL}/docs{value}"


def wiki_canonical_url(url: str, *, frontmatter_slug: str | None = None) -> str:
    """GitHub blob URL → Wiki route only with authoritative frontmatter slug.

    Args:
        url: 检索结果携带的文档 URL(可为任意来源,含空串)。

    Returns:
        有效 frontmatter slug 的 wiki-documents .md 文档 →
        ``{WIKI_BASE_URL}/docs/...``；slug 缺失/非法或其余一切(普通 GitHub
        仓库、官网、WooCommerce、结构异常)→ 原样。
    """
    if not url:
        return url
    m = _GITHUB_BLOB_RE.match(url)
    if not m:
        return url
    if f"/{WIKI_REPO}/blob/" not in url:
        return url

    path = m.group("path")
    if not path.endswith(_MD_SUFFIX):
        return url
    # An explicit authority is required. Missing authority is the legacy-object
    # case; preserve the known GitHub blob instead of guessing a Wiki route.
    if frontmatter_slug is None:
        return url
    return _canonical_url_from_slug(frontmatter_slug) or url
