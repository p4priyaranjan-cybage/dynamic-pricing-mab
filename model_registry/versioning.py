"""Model artifact versioning - timestamped directories with a 'current'
pointer for safe rollback.

Design:
  - Each save creates a new version directory: {base_dir}/{version_tag}/
  - A `current.txt` file in the parent directory points to the active version.
  - `load_or_create` always reads the 'current' pointer to find the right
    version. If no pointer exists, falls back to the legacy flat layout
    (backward-compatible with pre-versioning artifacts).
  - Rollback = overwrite `current.txt` with a previous version tag.
  - Cleanup: keeps the last N versions, deletes older ones.

See docs/ARCHITECTURE.md "Model Versioning" and docs/ARCHITECTURE_REVIEW.md
"Gap 6" for the design rationale.
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path


MAX_VERSIONS_KEPT = 5  # keep this many recent versions; older ones are pruned


def _version_tag() -> str:
    """Timestamp-based version tag (UTC), lexicographically sortable."""
    return dt.datetime.utcnow().strftime("v_%Y%m%d_%H%M%S")


def create_version_dir(base_dir: Path) -> Path:
    """Create a new timestamped version directory and update the 'current' pointer."""
    base_dir.mkdir(parents=True, exist_ok=True)
    tag = _version_tag()
    version_dir = base_dir / tag
    version_dir.mkdir(parents=True, exist_ok=True)
    # Update pointer
    (base_dir / "current.txt").write_text(tag)
    return version_dir


def get_current_version_dir(base_dir: Path) -> Path | None:
    """Resolve the current active version directory.

    Falls back to `base_dir` itself if no current.txt exists (backward
    compat with pre-versioning flat layout where .vw files live directly
    in base_dir).
    """
    pointer_file = base_dir / "current.txt"
    if pointer_file.exists():
        tag = pointer_file.read_text().strip()
        version_dir = base_dir / tag
        if version_dir.exists():
            return version_dir
    # Backward compat: if legacy .vw files exist directly in base_dir, use it
    if base_dir.exists() and any(base_dir.glob("*.vw")):
        return base_dir
    return None


def rollback(base_dir: Path, to_version: str | None = None) -> str | None:
    """Rollback to a previous version.

    If `to_version` is None, rolls back to the most recent version before
    the current one. Returns the version tag rolled back to, or None if
    rollback is not possible.
    """
    pointer_file = base_dir / "current.txt"
    if not pointer_file.exists():
        return None

    current_tag = pointer_file.read_text().strip()
    versions = sorted_versions(base_dir)

    if to_version:
        if (base_dir / to_version).exists():
            pointer_file.write_text(to_version)
            return to_version
        return None

    # Find the one before current
    try:
        idx = versions.index(current_tag)
    except ValueError:
        return None

    if idx <= 0:
        return None  # no earlier version to roll back to

    prev_tag = versions[idx - 1]
    pointer_file.write_text(prev_tag)
    return prev_tag


def sorted_versions(base_dir: Path) -> list[str]:
    """List all version tags in chronological order (oldest first)."""
    if not base_dir.exists():
        return []
    return sorted(
        d.name for d in base_dir.iterdir()
        if d.is_dir() and d.name.startswith("v_")
    )


def prune_old_versions(base_dir: Path, keep: int = MAX_VERSIONS_KEPT) -> list[str]:
    """Delete versions older than the most recent `keep`, never deletes current."""
    versions = sorted_versions(base_dir)
    if len(versions) <= keep:
        return []

    pointer_file = base_dir / "current.txt"
    current_tag = pointer_file.read_text().strip() if pointer_file.exists() else None

    to_delete = versions[:-keep]
    # Never delete the current version even if it's old
    to_delete = [v for v in to_delete if v != current_tag]

    deleted = []
    for v in to_delete:
        version_dir = base_dir / v
        if version_dir.exists():
            shutil.rmtree(version_dir)
            deleted.append(v)
    return deleted
