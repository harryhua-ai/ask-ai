"""#64 frontmatter authority propagation:connector → Weaviate → SearchResult."""

from types import SimpleNamespace


def test_github_connector_carries_frontmatter_slug(monkeypatch, tmp_path):
    from backend.connectors.github import GitHubConnector
    from backend.connectors.registry import SourceConfig

    cfg = SourceConfig(
        id="wiki",
        type="github",
        product="ask-ai",
        enabled=True,
        config={"repo_url": "https://github.com/camthink-ai/wiki-documents", "clone_path": str(tmp_path)},
        sync_interval="24h",
    )
    doc = GitHubConnector(cfg)._make_document(
        "docs/6-neoeyes-ne503-series/3-sdk/reference.md",
        "---\nslug: /neoeyes-ne503-series/sdk/reference\n---\n# SDK\n",
        "main",
    )
    assert doc.metadata["frontmatter_slug"] == "/neoeyes-ne503-series/sdk/reference"


def test_ingest_props_and_search_result_preserve_frontmatter_slug():
    from backend.connectors.base import RawDocument
    from backend.pipeline.chunk import Chunk
    from backend.pipeline.ingest import _build_props
    from backend.retrieval.search import HybridSearcher

    doc = RawDocument(
        source_id="wiki/main/reference.md",
        source_type="github",
        product="ask-ai",
        title="reference",
        content="# SDK",
        url="https://github.com/camthink-ai/wiki-documents/blob/main/docs/reference.md",
        metadata={"path": "docs/reference.md", "frontmatter_slug": "/sdk/reference"},
        content_hash="a" * 64,
        branch="main",
    )
    chunk = Chunk(
        text="# SDK",
        document=doc,
        chunk_index=0,
        total_chunks=1,
        start_char=0,
        end_char=5,
    )
    props = _build_props(chunk, doc)
    assert props["frontmatter_slug"] == "/sdk/reference"

    result = HybridSearcher.__new__(HybridSearcher)._to_search_result(
        SimpleNamespace(properties={**props}, metadata=None)
    )
    assert result.frontmatter_slug == "/sdk/reference"
