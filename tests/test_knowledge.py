import tempfile
import unittest
from pathlib import Path

from ai_code_review.infrastructure.knowledge import KnowledgeBase


class KnowledgeTests(unittest.TestCase):
    def test_chinese_rule_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            standard = root / "c.md"
            standard.write_text(
                """\
---
profile: embedded
languages: [c, cpp]
---

## C-ISR-001

中断服务程序禁止阻塞锁和动态内存分配。

## C-NAME-001

函数名称必须使用小写字母和下划线。
""",
                encoding="utf-8",
            )
            knowledge = KnowledgeBase(root, max_chars=2000, max_rules=1)

            result = knowledge.search(
                language="c",
                profile="embedded",
                query="void irq_handler(void) { mutex_lock(&lock); } // 中断中使用阻塞锁",
            )

            self.assertIn("C-ISR-001", result)
            self.assertNotIn("C-NAME-001", result)
