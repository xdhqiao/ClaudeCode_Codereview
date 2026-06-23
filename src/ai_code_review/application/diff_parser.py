from __future__ import annotations

import re
from dataclasses import dataclass, field


HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


@dataclass(slots=True)
class DiffLine:
    marker: str
    content: str
    old_line: int | None
    new_line: int | None

    @property
    def is_changed(self) -> bool:
        return self.marker in {"+", "-"}

    def render(self) -> str:
        old = str(self.old_line) if self.old_line is not None else ""
        new = str(self.new_line) if self.new_line is not None else ""
        return f"{self.marker} OLD={old:>6} NEW={new:>6} | {self.content}"


@dataclass(slots=True)
class DiffHunk:
    header: str
    old_start: int
    new_start: int
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def changed_line_count(self) -> int:
        return sum(line.is_changed for line in self.lines)

    @property
    def eligible_line_numbers(self) -> set[int]:
        result: set[int] = set()
        for line in self.lines:
            if not line.is_changed:
                continue
            if line.old_line is not None:
                result.add(line.old_line)
            if line.new_line is not None:
                result.add(line.new_line)
        return result

    def render(self) -> str:
        body = "\n".join(line.render() for line in self.lines)
        return f"{self.header}\n{body}"


@dataclass(slots=True)
class FileDiff:
    old_path: str
    new_path: str
    hunks: list[DiffHunk] = field(default_factory=list)
    is_binary: bool = False
    is_deleted: bool = False

    @property
    def path(self) -> str:
        return self.old_path if self.is_deleted else self.new_path

    @property
    def changed_line_count(self) -> int:
        return sum(hunk.changed_line_count for hunk in self.hunks)


def _clean_git_path(value: str) -> str:
    value = value.strip()
    if value == "/dev/null":
        return value
    if value.startswith(("a/", "b/")):
        return value[2:]
    return value.strip('"')


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: DiffHunk | None = None
    old_line = 0
    new_line = 0

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            match = re.match(r"^diff --git a/(.+) b/(.+)$", raw_line)
            if not match:
                current_file = None
                current_hunk = None
                continue
            current_file = FileDiff(old_path=match.group(1), new_path=match.group(2))
            files.append(current_file)
            current_hunk = None
            continue

        if current_file is None:
            continue
        if raw_line.startswith("Binary files ") or raw_line.startswith("GIT binary patch"):
            current_file.is_binary = True
            continue
        if raw_line.startswith("--- "):
            current_file.old_path = _clean_git_path(raw_line[4:])
            continue
        if raw_line.startswith("+++ "):
            current_file.new_path = _clean_git_path(raw_line[4:])
            current_file.is_deleted = current_file.new_path == "/dev/null"
            continue

        hunk_match = HUNK_RE.match(raw_line)
        if hunk_match:
            old_line = int(hunk_match.group("old_start"))
            new_line = int(hunk_match.group("new_start"))
            current_hunk = DiffHunk(
                header=raw_line,
                old_start=old_line,
                new_start=new_line,
            )
            current_file.hunks.append(current_hunk)
            continue

        if current_hunk is None or not raw_line:
            continue
        marker = raw_line[0]
        content = raw_line[1:]
        if marker == "+":
            current_hunk.lines.append(DiffLine(marker, content, None, new_line))
            new_line += 1
        elif marker == "-":
            current_hunk.lines.append(DiffLine(marker, content, old_line, None))
            old_line += 1
        elif marker == " ":
            current_hunk.lines.append(DiffLine(marker, content, old_line, new_line))
            old_line += 1
            new_line += 1
        elif marker == "\\":
            continue

    return [file for file in files if file.hunks or file.is_binary]


def batch_hunks(file_diff: FileDiff, max_chars: int) -> list[list[DiffHunk]]:
    batches: list[list[DiffHunk]] = []
    current: list[DiffHunk] = []
    current_size = 0

    fragments: list[DiffHunk] = []
    for hunk in file_diff.hunks:
        if len(hunk.render()) <= max_chars:
            fragments.append(hunk)
            continue

        part = DiffHunk(
            header=f"{hunk.header} [split]",
            old_start=hunk.old_start,
            new_start=hunk.new_start,
        )
        part_size = len(part.header) + 1
        for line in hunk.lines:
            line_size = len(line.render()) + 1
            if part.lines and part_size + line_size > max_chars:
                fragments.append(part)
                part = DiffHunk(
                    header=f"{hunk.header} [split]",
                    old_start=line.old_line or hunk.old_start,
                    new_start=line.new_line or hunk.new_start,
                )
                part_size = len(part.header) + 1
            part.lines.append(line)
            part_size += line_size
        if part.lines:
            fragments.append(part)

    for hunk in fragments:
        size = len(hunk.render())
        if current and current_size + size > max_chars:
            batches.append(current)
            current = []
            current_size = 0
        current.append(hunk)
        current_size += size
    if current:
        batches.append(current)
    return batches
