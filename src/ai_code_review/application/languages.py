from __future__ import annotations

from pathlib import Path


LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".java": "java",
    ".go": "golang",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "javascript",
    ".svelte": "javascript",
}

DEFAULT_IGNORED_PARTS = {
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "vendor",
    "third_party",
    "dist",
    "build",
    "target",
    "coverage",
    "generated",
}


def detect_language(path: str | Path) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower())


def is_supported_source(path: Path) -> bool:
    return detect_language(path) is not None

