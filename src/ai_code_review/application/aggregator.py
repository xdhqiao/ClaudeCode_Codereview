from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from ai_code_review.domain.models import (
    MAX_REVIEW_COMMENTS_LENGTH,
    AgentMetrics,
    ReviewIssue,
    ReviewResult,
)


SCORE_FIELDS = {
    "logic": "logic_score",
    "performance": "performance_score",
    "security": "security_score",
    "readable": "readable_score",
    "code_style": "code_style_score",
}


def _dedupe_key(issue: ReviewIssue) -> tuple[object, ...]:
    normalized = re.sub(r"\W+", "", issue.description.lower())[:120]
    return (issue.type, tuple(issue.issue_line_number), normalized)


def _severity_cap(severity: int) -> int:
    return {5: 49, 4: 64, 3: 79, 2: 89, 1: 95}[severity]


def aggregate_results(
    results: Iterable[tuple[ReviewResult, int]],
    *,
    comment_line_number: int,
    max_issues: int,
) -> ReviewResult:
    weighted_results = list(results)
    if not weighted_results:
        return ReviewResult(
            comments="未发现可审查的代码。",
            logic_score=100,
            performance_score=100,
            security_score=100,
            readable_score=100,
            code_style_score=100,
            comment_line_number=comment_line_number,
            issues=[],
        )

    total_weight = sum(max(weight, 1) for _, weight in weighted_results)
    scores: dict[str, int] = {}
    for issue_type, field_name in SCORE_FIELDS.items():
        value = sum(
            getattr(result, field_name) * max(weight, 1) for result, weight in weighted_results
        )
        score = round(value / total_weight)
        relevant = [
            issue
            for result, _ in weighted_results
            for issue in result.issues
            if issue.type == issue_type
        ]
        if relevant:
            score = min(score, min(_severity_cap(issue.severity) for issue in relevant))
        scores[field_name] = score

    seen: set[tuple[object, ...]] = set()
    issues: list[ReviewIssue] = []
    for result, _ in weighted_results:
        for issue in result.issues:
            key = _dedupe_key(issue)
            if key not in seen:
                seen.add(key)
                issues.append(issue)
    issues.sort(key=lambda item: (-item.severity, -item.confidence_level, item.type))
    issues = issues[:max_issues]

    comments = " ".join(
        dict.fromkeys(
            result.comments.strip()
            for result, _ in weighted_results
            if result.comments.strip()
        )
    )
    return ReviewResult(
        comments=(comments or "审查完成。")[:MAX_REVIEW_COMMENTS_LENGTH],
        comment_line_number=comment_line_number,
        issues=issues,
        **scores,
    )


def aggregate_metrics(metrics: Iterable[AgentMetrics]) -> AgentMetrics:
    items = list(metrics)
    usage_totals: defaultdict[str, int | float] = defaultdict(int)
    for item in items:
        for key, value in (item.usage or {}).items():
            if isinstance(value, (int, float)):
                usage_totals[key] += value
    return AgentMetrics(
        duration_ms=sum(item.duration_ms or 0 for item in items),
        num_turns=sum(item.num_turns or 0 for item in items),
        total_cost_usd=sum(item.total_cost_usd or 0.0 for item in items),
        usage=dict(usage_totals) or None,
    )
