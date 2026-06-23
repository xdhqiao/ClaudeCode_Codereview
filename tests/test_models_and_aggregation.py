import unittest

from pydantic import ValidationError

from ai_code_review.application.aggregator import aggregate_results
from ai_code_review.domain.models import (
    ReviewIssue,
    ReviewMode,
    ReviewResult,
    ReviewTaskCreate,
)


def make_result(*, score: int = 95, issues: list[ReviewIssue] | None = None) -> ReviewResult:
    return ReviewResult(
        comments="ok",
        logic_score=score,
        performance_score=score,
        security_score=score,
        readable_score=score,
        code_style_score=score,
        comment_line_number=0,
        issues=issues or [],
    )


class ModelsAndAggregationTests(unittest.TestCase):
    def test_issue_requires_a_line_number(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewIssue(
                description="missing line",
                type="logic",
                severity=3,
                confidence_level=0.9,
                suggestion="fix it",
                issue_line_number=[],
            )

    def test_issue_rejects_more_than_two_line_numbers(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewIssue(
                description="too many lines",
                type="logic",
                severity=3,
                confidence_level=0.9,
                suggestion="fix it",
                issue_line_number=[1, 2, 3],
            )

    def test_high_severity_caps_dimension_score(self) -> None:
        issue = ReviewIssue(
            description="authentication bypass",
            type="security",
            severity=5,
            confidence_level=0.98,
            suggestion="enforce authorization",
            issue_line_number=[20],
        )

        result = aggregate_results(
            [(make_result(score=99, issues=[issue]), 10)],
            comment_line_number=2,
            max_issues=10,
        )

        self.assertEqual(result.security_score, 49)
        self.assertEqual(result.logic_score, 99)
        self.assertEqual(result.comment_line_number, 2)

    def test_task_validates_source_and_diff_base_ref(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewTaskCreate(project_id="demo", target_ref="HEAD")
        with self.assertRaises(ValidationError):
            ReviewTaskCreate(
                project_id="demo",
                repo_url="https://example.com/repo.git",
                target_ref="HEAD",
            )

        task = ReviewTaskCreate(
            project_id="demo",
            local_path="/repos/demo",
            target_ref="HEAD",
            mode=ReviewMode.FULL,
        )

        self.assertEqual(task.mode, ReviewMode.FULL)
