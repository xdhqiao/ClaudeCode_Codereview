from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


def build_repository_guard(repository_path: Path):
    root = repository_path.resolve()

    async def guard(
        hook_input: dict[str, Any],
        _tool_use_id: str | None,
        _context: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = str(hook_input.get("tool_name", ""))
        tool_input = hook_input.get("tool_input") or {}
        if tool_name not in {"Read", "Glob", "Grep"} or not isinstance(tool_input, dict):
            return deny_tool("Only repository read/search tools are allowed")

        for key in ("pattern", "glob"):
            value = tool_input.get(key)
            if isinstance(value, str) and unsafe_pattern(value):
                return deny_tool(f"{tool_name} {key} must stay inside the repository")

        path_value = tool_input.get("file_path") or tool_input.get("path")
        if not path_value:
            return {}
        if not isinstance(path_value, str):
            return deny_tool(f"{tool_name} path must be a string")
        if path_value.startswith("~") or "\0" in path_value:
            return deny_tool(f"{tool_name} path must stay inside the repository")
        candidate = Path(path_value)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return deny_tool(f"{tool_name} path could not be resolved")
        if resolved != root and not resolved.is_relative_to(root):
            return deny_tool(f"{tool_name} path is outside the repository")
        return {}

    return guard


def unsafe_pattern(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return (
        PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ".." in PurePosixPath(normalized).parts
        or value.startswith("~")
        or "\0" in value
    )


def deny_tool(reason: str) -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
