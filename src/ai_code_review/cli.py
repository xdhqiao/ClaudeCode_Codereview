from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

import uvicorn

from ai_code_review.api.app import create_app
from ai_code_review.bootstrap import build_container
from ai_code_review.config import Settings
from ai_code_review.domain.models import ReviewMode, ReviewTaskCreate
from ai_code_review.infrastructure.knowledge import import_docx_standard


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-code-review")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="Start HTTP API and task workers")
    subparsers.add_parser("worker", help="Start task workers only")

    enqueue = subparsers.add_parser("enqueue", help="Create a review task")
    enqueue.add_argument("--project-id", required=True)
    source = enqueue.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo-url")
    source.add_argument("--local-path")
    enqueue.add_argument("--mode", choices=[item.value for item in ReviewMode], default="diff")
    enqueue.add_argument("--base-ref")
    enqueue.add_argument("--target-ref", default="HEAD")
    enqueue.add_argument("--profile", default="default")

    import_standard = subparsers.add_parser(
        "import-standard", help="Convert a Word standard into indexed Markdown"
    )
    import_standard.add_argument("source", type=Path)
    import_standard.add_argument("--id", required=True, dest="standard_id")
    import_standard.add_argument("--languages", default="all")
    import_standard.add_argument("--profile", default="default")
    import_standard.add_argument("--version", default="1.0")
    return parser


async def _run_worker() -> None:
    container = build_container()
    await container.storage.ping()
    await container.storage.ensure_indexes()
    try:
        await container.worker.run_forever()
    finally:
        container.storage.close()


async def _enqueue(args: argparse.Namespace) -> None:
    container = build_container()
    try:
        await container.storage.ping()
        await container.storage.ensure_indexes()
        task = await container.storage.enqueue(
            ReviewTaskCreate(
                project_id=args.project_id,
                repo_url=args.repo_url,
                local_path=args.local_path,
                base_ref=args.base_ref,
                target_ref=args.target_ref,
                mode=ReviewMode(args.mode),
                code_style_profile=args.profile,
            )
        )
        print(json.dumps(task.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2))
    finally:
        container.storage.close()


def main() -> None:
    args = _build_parser().parse_args()
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.command == "serve":
        uvicorn.run(
            create_app(build_container(settings)),
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
        )
    elif args.command == "worker":
        asyncio.run(_run_worker())
    elif args.command == "enqueue":
        asyncio.run(_enqueue(args))
    elif args.command == "import-standard":
        output = import_docx_standard(
            args.source,
            settings.knowledge_root,
            standard_id=args.standard_id,
            languages=[item.strip() for item in args.languages.split(",") if item.strip()],
            profile=args.profile,
            version=args.version,
        )
        print(output)


if __name__ == "__main__":
    main()

