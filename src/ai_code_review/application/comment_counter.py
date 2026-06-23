from __future__ import annotations

from collections.abc import Iterable


def count_comment_lines(lines: Iterable[str], language: str) -> int:
    """Count comment-bearing lines while ignoring markers inside simple strings."""
    return len(comment_line_numbers(lines, language))


def comment_line_numbers(
    lines: Iterable[str],
    language: str,
    *,
    start_line: int = 1,
) -> set[int]:
    result: set[int] = set()
    in_block = False
    hash_comments = language in {"python"}
    slash_line_comments = language in {
        "c",
        "cpp",
        "java",
        "golang",
        "javascript",
        "typescript",
    }
    slash_block_comments = slash_line_comments or language == "css"
    html_comments = language == "html"

    for line_number, original in enumerate(lines, start=start_line):
        line = original.strip()
        if not line:
            continue

        if html_comments:
            if in_block:
                result.add(line_number)
                if "-->" in line:
                    in_block = False
                continue
            if "<!--" in line:
                result.add(line_number)
                if "-->" not in line.split("<!--", 1)[1]:
                    in_block = True
            continue

        if slash_block_comments:
            if in_block:
                result.add(line_number)
                if "*/" in line:
                    in_block = False
                continue
            marker, position = _find_comment_marker(
                line,
                allow_hash=False,
                allow_slash=slash_line_comments,
                allow_block=True,
            )
            if marker:
                result.add(line_number)
                if marker == "/*" and "*/" not in line[position + 2 :]:
                    in_block = True
            continue

        if hash_comments:
            marker, _ = _find_comment_marker(
                line,
                allow_hash=True,
                allow_slash=False,
                allow_block=False,
            )
            if marker:
                result.add(line_number)

    return result


def _find_comment_marker(
    line: str,
    *,
    allow_hash: bool,
    allow_slash: bool,
    allow_block: bool,
) -> tuple[str | None, int]:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        character = line[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            index += 1
            continue
        pair = line[index : index + 2]
        if allow_slash and pair == "//":
            return "//", index
        if allow_block and pair == "/*":
            return "/*", index
        if allow_hash and character == "#":
            return "#", index
        index += 1
    return None, -1
