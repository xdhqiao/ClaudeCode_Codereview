import asyncio
import tempfile
import unittest
from pathlib import Path

from ai_code_review.infrastructure.repository_guard import build_repository_guard


class RepositoryGuardTests(unittest.TestCase):
    def test_allows_paths_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = build_repository_guard(root)

            result = asyncio.run(
                guard(
                    {"tool_name": "Read", "tool_input": {"file_path": "src/main.py"}},
                    None,
                    {},
                )
            )

            self.assertEqual(result, {})

    def test_denies_paths_and_patterns_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = build_repository_guard(root)

            path_result = asyncio.run(
                guard(
                    {"tool_name": "Read", "tool_input": {"file_path": "../secret.txt"}},
                    None,
                    {},
                )
            )
            pattern_result = asyncio.run(
                guard(
                    {"tool_name": "Glob", "tool_input": {"pattern": "/etc/**"}},
                    None,
                    {},
                )
            )
            home_result = asyncio.run(
                guard(
                    {"tool_name": "Read", "tool_input": {"file_path": "~/.ssh/config"}},
                    None,
                    {},
                )
            )

            self.assertEqual(
                path_result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertEqual(
                pattern_result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertEqual(
                home_result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
