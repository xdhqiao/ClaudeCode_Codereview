from __future__ import annotations

from dataclasses import dataclass

from ai_code_review.application.review_service import ReviewService
from ai_code_review.application.worker import ReviewWorker
from ai_code_review.config import Settings
from ai_code_review.infrastructure.claude_agent import ClaudeAgentReviewClient
from ai_code_review.infrastructure.git_repository import GitRepositoryManager
from ai_code_review.infrastructure.knowledge import KnowledgeBase
from ai_code_review.infrastructure.mongo_repository import MongoReviewRepository


@dataclass(slots=True)
class Container:
    settings: Settings
    storage: MongoReviewRepository
    worker: ReviewWorker
    knowledge: KnowledgeBase


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.knowledge_root.mkdir(parents=True, exist_ok=True)

    storage = MongoReviewRepository(settings.mongodb_uri, settings.mongodb_database)
    repository_manager = GitRepositoryManager(settings)
    knowledge = KnowledgeBase(
        settings.knowledge_root,
        settings.max_standard_chars,
        settings.max_standard_rules,
    )
    agent = ClaudeAgentReviewClient(settings)
    review_service = ReviewService(
        settings=settings,
        repository_manager=repository_manager,
        knowledge=knowledge,
        agent=agent,
        storage=storage,
    )
    worker = ReviewWorker(
        settings=settings,
        storage=storage,
        review_service=review_service,
    )
    return Container(settings=settings, storage=storage, worker=worker, knowledge=knowledge)
