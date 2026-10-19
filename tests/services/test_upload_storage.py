"""Fail-closed deletion boundaries for the application-owned upload tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services import upload_storage


def _config(root: Path, source_id: str) -> dict[str, object]:
    return {"upload_mode": True, "root_path": str(root / source_id)}


def test_remove_upload_tree_is_exact_and_keeps_literal_prefix_sibling(tmp_path: Path) -> None:
    root = tmp_path / "data-sources"
    own = root / "source-a"
    sibling = root / "source-a-copy"
    own.mkdir(parents=True)
    sibling.mkdir()
    (own / "remove.md").write_text("remove", encoding="utf-8")
    (sibling / "keep.md").write_text("keep", encoding="utf-8")

    assert upload_storage.remove_owned_upload_tree(
        "source-a", "filesystem", _config(root, "source-a"), uploads_root=root
    )

    assert not own.exists()
    assert (sibling / "keep.md").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("source_id", ["../escape", "a/b", r"a\b", ".", "..", ""])
def test_upload_source_identity_rejects_path_escape(tmp_path: Path, source_id: str) -> None:
    root = tmp_path / "data-sources"
    root.mkdir()
    with pytest.raises(RuntimeError, match="source_id"):
        upload_storage.validate_owned_upload_tree(
            source_id,
            "filesystem",
            _config(root, source_id),
            uploads_root=root,
        )


def test_symlinked_upload_tree_fails_closed_and_keeps_target(tmp_path: Path) -> None:
    root = tmp_path / "data-sources"
    target = tmp_path / "outside"
    root.mkdir()
    target.mkdir()
    (target / "keep.md").write_text("keep", encoding="utf-8")
    (root / "source-a").symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlink"):
        upload_storage.remove_owned_upload_tree(
            "source-a", "filesystem", _config(root, "source-a"), uploads_root=root
        )
    assert (target / "keep.md").read_text(encoding="utf-8") == "keep"


def test_nested_symlink_fails_before_any_tree_mutation(tmp_path: Path) -> None:
    root = tmp_path / "data-sources"
    own = root / "source-a"
    outside = tmp_path / "outside"
    own.mkdir(parents=True)
    outside.mkdir()
    (own / "own.md").write_text("own", encoding="utf-8")
    (outside / "keep.md").write_text("keep", encoding="utf-8")
    (own / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlink"):
        upload_storage.remove_owned_upload_tree(
            "source-a", "filesystem", _config(root, "source-a"), uploads_root=root
        )
    assert (own / "own.md").exists()
    assert (outside / "keep.md").exists()


def test_unknown_authoritative_parent_and_permission_failure_are_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_root = tmp_path / "missing"
    with pytest.raises(RuntimeError, match="authoritative uploads root"):
        upload_storage.remove_owned_upload_tree(
            "source-a",
            "filesystem",
            _config(missing_root, "source-a"),
            uploads_root=missing_root,
        )

    root = tmp_path / "data-sources"
    own = root / "source-a"
    own.mkdir(parents=True)
    (own / "blocked.md").write_text("blocked", encoding="utf-8")

    def _denied(path: Path) -> None:
        raise PermissionError("simulated upload permission denial")

    _denied.avoids_symlink_attacks = True  # type: ignore[attr-defined]
    monkeypatch.setattr(upload_storage.shutil, "rmtree", _denied)
    with pytest.raises(PermissionError, match="permission denial"):
        upload_storage.remove_owned_upload_tree(
            "source-a", "filesystem", _config(root, "source-a"), uploads_root=root
        )
    assert (own / "blocked.md").exists()


def test_non_upload_filesystem_never_touches_external_root(tmp_path: Path) -> None:
    external = tmp_path / "external-read-only-corpus"
    external.mkdir()
    (external / "keep.md").write_text("keep", encoding="utf-8")

    assert (
        upload_storage.remove_owned_upload_tree(
            "source-a",
            "filesystem",
            {"upload_mode": False, "root_path": str(external)},
            uploads_root=tmp_path / "does-not-exist",
        )
        is False
    )
    assert (external / "keep.md").exists()
