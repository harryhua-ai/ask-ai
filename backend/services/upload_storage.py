"""Application-owned upload corpus paths and fail-closed tree removal."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

# Single authoritative upload corpus root.  The production containers mount
# /app/data/uploads as one shared persistent volume, with CWD=/app.
UPLOADS_CORPUS_ROOT = Path("data/uploads/data-sources")


def upload_root(source_id: str) -> Path:
    return UPLOADS_CORPUS_ROOT / source_id


def _validate_source_component(source_id: str) -> None:
    if (
        not source_id
        or source_id in {".", ".."}
        or "/" in source_id
        or "\\" in source_id
        or "\x00" in source_id
        or Path(source_id).name != source_id
    ):
        raise RuntimeError(f"unsafe upload source_id identity: {source_id!r}")


def validate_owned_upload_tree(
    source_id: str,
    source_type: str,
    config: dict[str, Any] | None,
    *,
    uploads_root: Path = UPLOADS_CORPUS_ROOT,
) -> Path | None:
    """Return the exact owned subtree, or None for a non-upload source.

    Upload-mode declarations are authoritative only for filesystem sources whose
    configured root is the exact direct child assigned by the application.
    Ambiguous ownership or filesystem shape is an error, never a silent skip.
    """
    values = config or {}
    if values.get("upload_mode") is not True:
        return None
    if source_type != "filesystem":
        raise RuntimeError("upload_mode ownership requires a filesystem source")
    _validate_source_component(source_id)

    root = Path(uploads_root)
    if root.is_symlink() or not root.exists() or not root.is_dir():
        raise RuntimeError(f"authoritative uploads root is unavailable or unsafe: {root}")
    expected = root / source_id
    configured = values.get("root_path")
    if not isinstance(configured, str) or Path(configured) != expected:
        raise RuntimeError(
            f"upload root_path identity mismatch for source {source_id}: {configured!r}"
        )
    if expected.parent != root:
        raise RuntimeError(f"upload subtree escaped its lexical parent: {expected}")
    if expected.is_symlink():
        raise RuntimeError(f"upload source subtree must not be a symlink: {expected}")

    root_resolved = root.resolve(strict=True)
    target_resolved = expected.resolve(strict=False)
    if target_resolved.parent != root_resolved:
        raise RuntimeError(f"upload source subtree escaped the authoritative root: {expected}")
    if expected.exists() and not expected.is_dir():
        raise RuntimeError(f"upload source subtree is not a directory: {expected}")

    if expected.exists():
        for current, dirnames, filenames in os.walk(expected, followlinks=False):
            current_path = Path(current)
            for name in [*dirnames, *filenames]:
                entry = current_path / name
                if entry.is_symlink():
                    raise RuntimeError(f"symlink found inside upload source subtree: {entry}")
                resolved = entry.resolve(strict=True)
                if target_resolved != resolved and target_resolved not in resolved.parents:
                    raise RuntimeError(f"upload entry escaped its source subtree: {entry}")
    return expected


def remove_owned_upload_tree(
    source_id: str,
    source_type: str,
    config: dict[str, Any] | None,
    *,
    uploads_root: Path = UPLOADS_CORPUS_ROOT,
) -> bool:
    """Remove one validated upload subtree and verify its absence.

    Missing source directories are an idempotent success only after the shared
    authoritative parent and exact configured ownership have been validated.
    """
    target = validate_owned_upload_tree(
        source_id, source_type, config, uploads_root=uploads_root
    )
    if target is None or not target.exists():
        return False
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        raise RuntimeError("platform cannot guarantee symlink-safe upload tree removal")
    shutil.rmtree(target)
    if target.exists() or target.is_symlink():
        raise RuntimeError(f"upload source subtree remains after removal: {target}")
    return True
