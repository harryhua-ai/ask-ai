"""Issue #48 RED evidence — linkability authority absent from citation output.

Track C contract (docs/v164-iteration-contracts-20260913 §1 C-3/C-4):
backend citation output must own explicit link state (valid external /
non-navigable / private-or-inaccessible / stale-or-unavailable) so the
widget never infers linkability from string shape; moved/renamed
branch-ref targets must be truthful about staleness.

Production truth (2026-09-15, read-only probes):
- wiki-documents `4-application-guide/1-app-development/` subtree was
  moved/removed on main; the NE503 "2-sdk-reference" chunk's blob URL
  returns HTTP 404 anonymously, while the same citation serializes as a
  plain http(s) URL indistinguishable from a live canonical URL.
- knowledge-case sources are serialized with url="" and render in the
  widget as a clickable `<a href="">` (fake self-navigation).

These tests are RED on main by design: they assert the CONTRACT-required
distinguishability, not a specific implementation vocabulary.
"""

from types import SimpleNamespace

import pytest

from backend.connectors.github import GitHubConnector
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

WIKI_BLOB = "https://github.com/camthink-ai/wiki-documents/blob/main"
# Production-verified moved path (anonymous HEAD -> 404 on 2026-09-15):
SDK_REF_MOVED_BLOB = (
    f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/4-application-guide/"
    "1-app-development/reference/2-sdk-reference.md"
)
LIVE_BLOB = "https://github.com/camthink-ai/neoruntime/blob/main/docker/dev/build.sh"

# Any explicit linkability vocabulary satisfies Track C C-3; the defect is
# that NO state marker exists at all on main.
STATE_KEYS = {
    "link_state",
    "linkability",
    "navigation_state",
    "navigable",
    "clickable",
    "url_state",
    "visitor_reachability",
}


def _sr(url: str, title: str, source_type: str = "github") -> SearchResult:
    return SearchResult(
        text="chunk text",
        source_id=f"src/{title}",
        source_type=source_type,
        product="ne503",
        title=title,
        url=url,
        score=0.9,
        chunk_index=0,
    )


def _sources_for(reranked):
    orchestrator = RAGOrchestrator.__new__(RAGOrchestrator)
    return orchestrator._collect_public_sources(reranked)


@pytest.mark.unit
def test_issue48_red_stale_branch_ref_citation_has_no_link_state():
    """RED(C-3/C-4): moved-path citation serializes identical to a live URL."""
    sources = _sources_for(
        [_sr(SDK_REF_MOVED_BLOB, "2-sdk-reference"), _sr(LIVE_BLOB, "build")]
    )
    stale = next(s for s in sources if s["title"] == "2-sdk-reference")
    assert any(k in stale for k in STATE_KEYS), (
        "Track C C-3/C-4 RED: stale branch-ref citation carries no explicit "
        f"link state; serialized citation = {sorted(stale)} — the widget can "
        "only guess linkability from string shape (fake navigability)"
    )


@pytest.mark.unit
def test_issue48_red_private_repo_document_has_no_reachability_state():
    """RED(C-4): token-cloned private repo still gets a public-looking blob URL."""
    stub = SimpleNamespace(
        _config=SimpleNamespace(id="privsrc"),
        product="t",
        _owner="camthink-ai",
        _repo="some-private-repo",
        _channel_visibility=("api",),
    )
    doc = GitHubConnector._make_document(stub, "docs/x.md", "content", "main")
    assert doc.url == "https://github.com/camthink-ai/some-private-repo/blob/main/docs/x.md"
    assert any(k in doc.metadata for k in STATE_KEYS), (
        "Track C C-4 RED: connector emits a public-looking canonical blob URL "
        "for a token-accessed repo with no accessibility/reachability state "
        f"(metadata keys = {sorted(doc.metadata)})"
    )
