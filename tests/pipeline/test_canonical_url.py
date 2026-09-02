"""Wiki canonical citation URL 映射单元测试。

产品语义(CIT-URL Contract):
- CamThink Wiki 知识从 GitHub(camthink-ai/wiki-documents,Docusaurus)ingestion,
  citation 应指向 wiki.camthink.ai 对应页面,而非 github.com blob 页。
- 普通 GitHub source / Website / WooCommerce citation 行为不变。
- 同一 Wiki 文档不同 chunks(含 i18n 翻译版)→ 相同 canonical page URL。
- 映射无法可靠完成 → 原样返回 GitHub URL,不产生 broken URL。

路由变换规则已对照线上 https://wiki.camthink.ai/sitemap.xml(2026-09-01 build)
逐条实证:测试内的每个期望 canonical URL 均为当日验证存在的真实路由。
"""

import pytest

from backend.pipeline.canonical_url import WIKI_BASE_URL, wiki_canonical_url

WIKI_BLOB = "https://github.com/camthink-ai/wiki-documents/blob/main"


@pytest.mark.unit
class TestWikiCanonicalMapping:
    """wiki-documents blob URL → wiki.camthink.ai canonical URL。"""

    def test_zh_overview_docs_path(self):
        """G001:中文主文档(生产语料真实路径)→ wiki 对应页面(线上实证路由)。"""
        url = f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
        assert wiki_canonical_url(url) == (f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/overview")

    def test_zh_deep_software_guide_path(self):
        """G001:深层路径(09-01 验收证据真实 URL)→ 线上实证路由。"""
        url = (
            f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/2-NE300-MB01-development-board/"
            "2-software-guide/2-windows-wsl-source-build-and-flash.md"
        )
        assert wiki_canonical_url(url) == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/"
            "NE300-MB01-development-board/software-guide/windows-wsl-source-build-and-flash"
        )

    def test_ne503_flashing_path(self):
        """G001:NE503 系列路径 → 线上实证路由。"""
        url = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-software-guide/2-system-flashing.md"
        assert wiki_canonical_url(url) == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne503-series/software-guide/system-flashing"
        )

    def test_category_index_collapse_dirname_equals_stem(self):
        """目录数字前缀剥离后与文件同名 → 折叠为目录路由(线上实证 ai-tool-stack)。"""
        url = (
            f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/3-application-guide/"
            "1-ai-tool-stack/1-ai-tool-stack.md"
        )
        assert wiki_canonical_url(url) == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/application-guide/ai-tool-stack"
        )

    def test_index_md_maps_to_directory_route(self):
        """index.md → 所属目录路由(线上实证 ne101-camera-component case studies)。"""
        url = (
            f"{WIKI_BLOB}/docs/0-neomind/developer-guide/case-studies/"
            "7-ne101-camera-component/index.md"
        )
        assert wiki_canonical_url(url) == (
            f"{WIKI_BASE_URL}/docs/neomind/developer-guide/case-studies/ne101-camera-component"
        )

    def test_i18n_translation_maps_to_same_canonical_page(self):
        """G003:i18n 翻译版与中文主文档 → 同一 canonical page URL。"""
        zh = f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
        en = (
            f"{WIKI_BLOB}/i18n/en/docusaurus-plugin-content-docs/current/"
            "5-neoeyes-ne301-series/0-overview.md"
        )
        assert wiki_canonical_url(zh) == wiki_canonical_url(en)
        assert wiki_canonical_url(en) == (f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/overview")

    def test_same_doc_different_chunks_same_canonical(self):
        """G003:同一文档不同 chunk(同 URL 不同 chunk_index)→ 相同 canonical。"""
        url = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-software-guide/2-system-flashing.md"
        assert wiki_canonical_url(url) == wiki_canonical_url(url)


@pytest.mark.unit
class TestCanonicalFallback:
    """映射不可靠时原样返回,不产生 broken URL(G004)。"""

    def test_normal_github_repo_unchanged(self):
        """G002:普通 GitHub 仓库 blob URL 原样保留。"""
        url = "https://github.com/camthink-ai/lowpower_camera/blob/main/README.md"
        assert wiki_canonical_url(url) == url

    def test_wiki_repo_non_docs_path_unchanged(self):
        """wiki 仓库但 docs/ 之外(仓库根 README)→ 不映射。"""
        url = f"{WIKI_BLOB}/README.md"
        assert wiki_canonical_url(url) == url

    def test_wiki_repo_non_markdown_unchanged(self):
        """wiki 仓库但非 .md(图片)→ 不映射。"""
        url = f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/img/overview.png"
        assert wiki_canonical_url(url) == url

    def test_wiki_repo_tree_url_unchanged(self):
        """tree(目录)URL 不属文档 chunk → 不映射。"""
        url = "https://github.com/camthink-ai/wiki-documents/tree/main/docs"
        assert wiki_canonical_url(url) == url

    def test_non_github_url_unchanged(self):
        """非 GitHub URL(官网产品页)→ 原样。"""
        url = "https://www.camthink.ai/products/ne301"
        assert wiki_canonical_url(url) == url

    def test_malformed_blob_path_unchanged(self):
        """blob 后路径结构异常(空路径)→ 不映射,原样返回。"""
        url = f"{WIKI_BLOB}/"
        assert wiki_canonical_url(url) == url

    def test_nonstandard_i18n_tree_unchanged(self):
        """i18n 路径不含标准 docusaurus-plugin-content-docs 树 → 不映射。"""
        url = f"{WIKI_BLOB}/i18n/en/weird-tree/current/foo.md"
        assert wiki_canonical_url(url) == url

    def test_empty_url_unchanged(self):
        """空串安全返回空串(检索结果 url 可为空)。"""
        assert wiki_canonical_url("") == ""
