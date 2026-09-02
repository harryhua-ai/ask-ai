"""Wiki canonical citation URL 映射。

产品语义(CIT-URL Contract):CamThink Wiki 知识从 GitHub
(camthink-ai/wiki-documents,Docusaurus 站点)ingestion,回答中的
citation 应指向 wiki.camthink.ai 对应页面,而非 github.com blob 页;
ingestion/provenance 源(GitHub)与用户可见 canonical URL 是两回事。

变换规则(对照线上 https://wiki.camthink.ai/sitemap.xml 逐条实证):
- 仅匹配 ``github.com/camthink-ai/wiki-documents/blob/<branch>/<path>``
  的 ``.md`` 文档,其余 URL 一律原样返回(普通 GitHub citation、
  Website / WooCommerce 行为不变)。
- ``i18n/<locale>/docusaurus-plugin-content-docs/current/docs/…`` 翻译树
  镜像到默认 locale 的同一 canonical 页面(与 rag 的来源去重语义一致)。
- 逐段剥离 Docusaurus number prefix(``5-neoeyes-…`` → ``neoeyes-…``)。
- ``index.md`` 或「剥离前缀后与父目录同名」的文件视为目录索引页,
  折叠为目录路由。
- 任何结构意外(docs/ 之外、非 .md、空路径等)→ 原样返回 GitHub URL,
  不产生猜测性 broken URL(CIT-URL-G004 fallback)。

已知残留失配:线上部署构建滞后于仓库 main 时,个别改名的页面可能
404(线上为 SPA 兜底,表现为软 404)。该失配属于部署节奏问题,不在本
模块解决;存量语料的 URL 已固化在 Weaviate,本模块在展示层做映射,
不要求语料回灌(生产 backfill 另行立项)。
"""

import re

# wiki 站点与源仓库(产品拍板的唯一映射目标;如换仓/换域,改这两个常量)
WIKI_BASE_URL = "https://wiki.camthink.ai"
WIKI_REPO = "camthink-ai/wiki-documents"

# github blob URL:严格匹配 owner/repo/blob/branch/path 四段结构
_GITHUB_BLOB_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/blob/[^/]+/(?P<path>.+)$")
# i18n 翻译树前缀 → docs 内容相对路径(current/ 后直接镜像 docs/ 内容,
# 不含 docs/ 段本身;个别旧结构带 docs/ 段时兼容)
_I18N_DOCS_RE = re.compile(r"^i18n/[^/]+/docusaurus-plugin-content-docs/current/(?:docs/)?(.+)$")
# Docusaurus number prefix(如 ``5-`` / ``10-``)
_NUM_PREFIX_RE = re.compile(r"^\d+-")
_MD_SUFFIX = ".md"
_DOCS_DIR = "docs/"


def wiki_canonical_url(url: str) -> str:
    """GitHub blob URL → wiki canonical URL;不适用/不可靠时原样返回。

    Args:
        url: 检索结果携带的文档 URL(可为任意来源,含空串)。

    Returns:
        wiki-documents 的 .md 文档 → ``{WIKI_BASE_URL}/docs/...``;
        其余一切(普通 GitHub 仓库、官网、WooCommerce、结构异常)→ 原样。
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
    i18n = _I18N_DOCS_RE.match(path)
    if i18n:
        rel = f"{_DOCS_DIR}{i18n.group(1)}"
    else:
        rel = path
    if not rel.startswith(_DOCS_DIR):
        return url

    rel = rel[len(_DOCS_DIR) :]
    if not rel:
        return url
    segments = rel.split("/")
    dirs = [_NUM_PREFIX_RE.sub("", seg) for seg in segments[:-1]]
    if any(not seg for seg in dirs):
        return url
    stem = _NUM_PREFIX_RE.sub("", segments[-1][: -len(_MD_SUFFIX)])
    if not stem:
        return url
    # index.md / 与父目录同名(剥前缀后)→ Docusaurus 目录索引页
    if stem == "index" or (dirs and stem == dirs[-1]):
        parts = dirs
    else:
        parts = [*dirs, stem]
    if not parts:
        return url
    return f"{WIKI_BASE_URL}/docs/{'/'.join(parts)}"
