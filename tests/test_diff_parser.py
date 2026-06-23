import unittest

from ai_code_review.application.diff_parser import batch_hunks, parse_unified_diff


class DiffParserTests(unittest.TestCase):
    def test_parse_unified_diff_tracks_old_and_new_lines(self) -> None:
        diff = """\
diff --git a/demo.py b/demo.py
--- a/demo.py
+++ b/demo.py
@@ -10,3 +10,4 @@
 keep()
-old()
+new()
+added()
 tail()
"""

        files = parse_unified_diff(diff)

        self.assertEqual(len(files), 1)
        lines = files[0].hunks[0].lines
        self.assertEqual(
            [(line.marker, line.old_line, line.new_line) for line in lines],
            [
                (" ", 10, 10),
                ("-", 11, None),
                ("+", None, 11),
                ("+", None, 12),
                (" ", 12, 13),
            ],
        )

    def test_parse_deleted_file_uses_old_path(self) -> None:
        diff = """\
diff --git a/old.c b/old.c
deleted file mode 100644
--- a/old.c
+++ /dev/null
@@ -1 +0,0 @@
-int value;
"""

        file_diff = parse_unified_diff(diff)[0]

        self.assertTrue(file_diff.is_deleted)
        self.assertEqual(file_diff.path, "old.c")

    def test_large_single_hunk_is_split_to_prompt_sized_fragments(self) -> None:
        added = "\n".join(f"+value_{index} = {index}" for index in range(100))
        diff = f"""\
diff --git a/demo.py b/demo.py
--- a/demo.py
+++ b/demo.py
@@ -0,0 +1,100 @@
{added}
"""
        file_diff = parse_unified_diff(diff)[0]

        batches = batch_hunks(file_diff, max_chars=300)

        self.assertGreater(len(batches), 1)
        self.assertEqual(
            sum(hunk.changed_line_count for batch in batches for hunk in batch),
            100,
        )
