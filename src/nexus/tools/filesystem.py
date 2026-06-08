"""
Filesystem tools for NEXUS — write_file and edit_file.

Mirrors dexter's filesystem/write-file.ts and filesystem/edit-file.ts.
Requires user approval for write operations (same as dexter's approach).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


# Project root — all file operations are scoped to this directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)))


def _safe_path(filepath: str) -> str:
    """
    Resolve and validate the path is within the project root.
    Prevents path traversal attacks.
    """
    # Resolve to absolute path
    if not os.path.isabs(filepath):
        filepath = os.path.join(PROJECT_ROOT, filepath)

    resolved = os.path.realpath(filepath)
    root_resolved = os.path.realpath(PROJECT_ROOT)

    if not resolved.startswith(root_resolved):
        raise ValueError(
            f"Path '{filepath}' is outside the project root. "
            f"File operations are restricted to {PROJECT_ROOT}"
        )

    return resolved


async def write_file(filepath: str, content: str) -> dict[str, Any]:
    """
    Write content to a file, creating it if it doesn't exist.
    Creates parent directories automatically.

    Args:
        filepath: Path relative to project root or absolute path within root
        content: File content to write

    Returns:
        dict with status, path, and bytes_written
    """
    safe_path = _safe_path(filepath)

    # Create parent directories
    parent = os.path.dirname(safe_path)
    os.makedirs(parent, exist_ok=True)

    # Write file
    with open(safe_path, "w", encoding="utf-8") as f:
        f.write(content)

    return {
        "status": "success",
        "path": safe_path,
        "bytes_written": len(content),
        "message": f"Successfully wrote {len(content)} bytes to {filepath}",
    }


async def edit_file(
    filepath: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    """
    Edit a file by replacing a specific string.

    Args:
        filepath: Path relative to project root or absolute path within root
        old_string: Exact text to find and replace
        new_string: Replacement text
        replace_all: If True, replace all occurrences. Default: first occurrence only.

    Returns:
        dict with status, path, and replacements count
    """
    safe_path = _safe_path(filepath)

    if not os.path.exists(safe_path):
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(safe_path, "r", encoding="utf-8") as f:
        content = f.read()

    if old_string not in content:
        raise ValueError(
            f"String not found in {filepath}: '{old_string[:50]}...'"
        )

    if replace_all:
        count = content.count(old_string)
        new_content = content.replace(old_string, new_string)
    else:
        count = 1
        new_content = content.replace(old_string, new_string, 1)

    with open(safe_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return {
        "status": "success",
        "path": safe_path,
        "replacements": count,
        "message": f"Successfully made {count} replacement(s) in {filepath}",
    }


async def read_file(
    filepath: str,
    offset: int = 1,
    limit: int = 500,
) -> dict[str, Any]:
    """
    Read a file with line-based pagination.

    Args:
        filepath: Path relative to project root or absolute path within root
        offset: Line number to start from (1-indexed)
        limit: Maximum number of lines to return

    Returns:
        dict with content, total_lines, path
    """
    safe_path = _safe_path(filepath)

    if not os.path.exists(safe_path):
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(safe_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total_lines = len(lines)
    start = offset - 1
    end = start + limit
    selected = lines[start:end]

    return {
        "content": "".join(selected),
        "total_lines": total_lines,
        "path": safe_path,
        "lines_read": len(selected),
    }
