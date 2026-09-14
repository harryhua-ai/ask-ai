"""Wiki canonical citation URL 映射单元测试。

产品语义(CIT-URL Contract):
- 新摄取的 CamThink Wiki 知识从 GitHub(camthink-ai/wiki-documents,Docusaurus)
  带 authority slug 时,citation 指向 wiki.camthink.ai 对应页面。
- 存量对象缺 authority slug 时,citation 保留 GitHub blob,不猜 Wiki route。
- 普通 GitHub source / Website / WooCommerce citation 行为不变。
- 同一 Wiki 文档不同 chunks(含 i18n 翻译版)→ 相同 canonical page URL。
- 映射无法可靠完成 → 原样返回 GitHub URL,不产生 broken URL。

测试内的 canonical 期望值来自显式 frontmatter slug；未对目录名做隐式路由推断。
"""

import pytest

from backend.pipeline.canonical_url import (
    WIKI_BASE_URL,
    extract_frontmatter_slug,
    wiki_canonical_url,
)

WIKI_BLOB = "https://github.com/camthink-ai/wiki-documents/blob/main"


@pytest.mark.unit
class TestWikiCanonicalMapping:
    """wiki-documents blob URL → wiki.camthink.ai canonical URL。"""

    def test_zh_overview_docs_path(self):
        """G001:新摄取对象有 frontmatter authority → wiki 对应页面。"""
        url = f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
        assert wiki_canonical_url(url, frontmatter_slug="/neoeyes-ne301-series/overview") == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/overview"
        )

    def test_zh_deep_software_guide_path(self):
        """G001:深层文档的 frontmatter authority → 对应 Wiki 路由。"""
        url = (
            f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/2-NE300-MB01-development-board/"
            "2-software-guide/2-windows-wsl-source-build-and-flash.md"
        )
        assert wiki_canonical_url(
            url,
            frontmatter_slug=(
                "/neoeyes-ne301-series/NE300-MB01-development-board/"
                "software-guide/windows-wsl-source-build-and-flash"
            ),
        ) == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/"
            "NE300-MB01-development-board/software-guide/windows-wsl-source-build-and-flash"
        )

    def test_ne503_flashing_path(self):
        """G001:NE503 新摄取文档的 frontmatter authority → Wiki 路由。"""
        url = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-software-guide/2-system-flashing.md"
        assert wiki_canonical_url(
            url, frontmatter_slug="/neoeyes-ne503-series/software-guide/system-flashing"
        ) == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne503-series/software-guide/system-flashing"
        )

    def test_category_index_collapse_dirname_equals_stem(self):
        """新摄取对象的显式 slug 可表达目录索引语义。"""
        url = (
            f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/3-application-guide/"
            "1-ai-tool-stack/1-ai-tool-stack.md"
        )
        assert wiki_canonical_url(
            url, frontmatter_slug="/neoeyes-ne301-series/application-guide/ai-tool-stack"
        ) == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/application-guide/ai-tool-stack"
        )

    def test_index_md_maps_to_directory_route(self):
        """新摄取 index 文档的显式 slug → 目录路由。"""
        url = (
            f"{WIKI_BLOB}/docs/0-neomind/developer-guide/case-studies/"
            "7-ne101-camera-component/index.md"
        )
        assert wiki_canonical_url(
            url,
            frontmatter_slug=(
                "/neomind/developer-guide/case-studies/ne101-camera-component"
            ),
        ) == (
            f"{WIKI_BASE_URL}/docs/neomind/developer-guide/case-studies/ne101-camera-component"
        )

    def test_i18n_translation_maps_to_same_canonical_page(self):
        """G003:i18n 新摄取对象携带同一 slug → 同一 canonical page URL。"""
        zh = f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
        en = (
            f"{WIKI_BLOB}/i18n/en/docusaurus-plugin-content-docs/current/"
            "5-neoeyes-ne301-series/0-overview.md"
        )
        slug = "/neoeyes-ne301-series/overview"
        assert wiki_canonical_url(zh, frontmatter_slug=slug) == wiki_canonical_url(
            en, frontmatter_slug=slug
        )
        assert wiki_canonical_url(en, frontmatter_slug=slug) == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne301-series/overview"
        )

    def test_same_doc_different_chunks_same_canonical(self):
        """G003:同一文档不同 chunk 共享同一 authoritative slug。"""
        url = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-software-guide/2-system-flashing.md"
        slug = "/neoeyes-ne503-series/software-guide/system-flashing"
        assert wiki_canonical_url(url, frontmatter_slug=slug) == wiki_canonical_url(
            url, frontmatter_slug=slug
        )

    def test_frontmatter_slug_is_authoritative_over_path_guess(self):
        """#64:实际 Docusaurus slug 覆盖目录名推导。"""
        url = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-sdk/reference.md"
        assert wiki_canonical_url(url, frontmatter_slug="/neoeyes-ne503-series/sdk/reference") == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne503-series/sdk/reference"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "docs/6-neoeyes-ne503-series/3-sdk/reference.md",
            "docs/6-neoeyes-ne503-series/4-application-guide/3-resources.md",
        ],
    )
    def test_legacy_ne503_sdk_resources_without_slug_preserves_blob_authority(self, path):
        """#64 legacy regression:无 frontmatter authority 不得猜 Wiki route。"""
        url = f"{WIKI_BLOB}/{path}"
        assert wiki_canonical_url(url, frontmatter_slug=None) == url
        assert not wiki_canonical_url(url, frontmatter_slug=None).startswith(WIKI_BASE_URL)

    def test_frontmatter_slug_trailing_slash_is_preserved_as_route_semantics(self):
        url = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/4-application-guide/3-resources.md"
        assert wiki_canonical_url(url, frontmatter_slug="/neoeyes-ne503-series/application-guide/") == (
            f"{WIKI_BASE_URL}/docs/neoeyes-ne503-series/application-guide/"
        )

    @pytest.mark.parametrize("slug", ["https://evil.example/route", "../not-a-slug", "", 123])
    def test_invalid_frontmatter_slug_does_not_fall_back_to_guessed_route(self, slug):
        url = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-sdk/reference.md"
        assert wiki_canonical_url(url, frontmatter_slug=slug) == url


@pytest.mark.unit
class TestFrontmatterExtraction:
    def test_extracts_docusaurus_slug_only_from_frontmatter(self):
        content = "---\ntitle: SDK\nslug: /neoeyes-ne503-series/sdk/reference\n---\n# SDK\n"
        assert extract_frontmatter_slug(content) == "/neoeyes-ne503-series/sdk/reference"

    def test_extracts_quoted_slug_and_distinguishes_absent_authority(self):
        assert extract_frontmatter_slug("---\nslug: '/sdk/reference'\n---\n") == "/sdk/reference"
        assert extract_frontmatter_slug("# no frontmatter\n") is None


@pytest.mark.unit
class TestCanonicalFallback:
    """authority 不足时原样返回,不产生 broken URL(G004)。"""

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
