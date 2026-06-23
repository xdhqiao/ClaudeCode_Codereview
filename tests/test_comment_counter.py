import unittest

from ai_code_review.application.comment_counter import (
    comment_line_numbers,
    count_comment_lines,
)


class CommentCounterTests(unittest.TestCase):
    def test_counts_c_block_and_line_comments(self) -> None:
        lines = [
            "int value = 1; // reason",
            "/* start",
            " * detail",
            " */",
            "return value;",
        ]

        self.assertEqual(count_comment_lines(lines, "c"), 4)

    def test_counts_python_comment_lines(self) -> None:
        lines = ["value = 1", "# explanation", "value += 1  # increment"]

        self.assertEqual(count_comment_lines(lines, "python"), 2)

    def test_ignores_comment_markers_inside_strings(self) -> None:
        c_lines = ['const char *url = "https://example.com/path";', "return 0;"]
        python_lines = ['value = "# not a comment"', "return value"]

        self.assertEqual(count_comment_lines(c_lines, "c"), 0)
        self.assertEqual(count_comment_lines(python_lines, "python"), 0)

    def test_returns_comment_line_numbers_for_block_comments(self) -> None:
        lines = ["/* start", "new line", "end */", "int value;"]

        self.assertEqual(comment_line_numbers(lines, "c"), {1, 2, 3})
