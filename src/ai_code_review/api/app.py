from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from hmac import compare_digest
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from ai_code_review.bootstrap import Container, build_container
from ai_code_review.domain.models import ReviewTaskCreate


def create_app(container: Container | None = None, *, run_worker: bool = True) -> FastAPI:
    app_container = container or build_container()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app_container.storage.ping()
        await app_container.storage.ensure_indexes()
        app.state.container = app_container
        worker_task: asyncio.Task[None] | None = None
        if run_worker:
            worker_task = asyncio.create_task(
                app_container.worker.run_forever(), name="review-worker-pool"
            )
        try:
            yield
        finally:
            app_container.worker.stop()
            if worker_task:
                await worker_task
            app_container.storage.close()

    app = FastAPI(
        title="AI Code Review Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        configured = app_container.settings.service_api_key
        if configured and request.url.path != "/health":
            supplied = request.headers.get("X-API-Key", "")
            expected = configured.get_secret_value()
            if not supplied or not compare_digest(supplied, expected):
                return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
        return await call_next(request)

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        await request.app.state.container.storage.ping()
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        container = request.app.state.container
        await container.storage.ping()
        settings = container.settings
        if not (
            settings.anthropic_api_key
            or settings.anthropic_auth_token
            or settings.anthropic_base_url
        ):
            raise HTTPException(
                status_code=503,
                detail="Model API configuration is missing",
            )
        return {"status": "ready"}

    @app.post("/api/v1/tasks", status_code=status.HTTP_202_ACCEPTED)
    async def create_task(request: Request, body: ReviewTaskCreate) -> dict[str, object]:
        try:
            task = await request.app.state.container.storage.enqueue(body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return task.model_dump(by_alias=True, mode="json")

    @app.get("/api/v1/tasks/{task_id}")
    async def get_task(request: Request, task_id: str) -> dict[str, object]:
        task = await request.app.state.container.storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.model_dump(by_alias=True, mode="json")

    @app.get("/api/v1/tasks/{task_id}/results")
    async def get_results(
        request: Request,
        task_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        task = await request.app.state.container.storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        records = await request.app.state.container.storage.list_results(
            task_id,
            offset=offset,
            limit=limit,
        )
        return [record.model_dump(by_alias=True, mode="json") for record in records]

    @app.get("/api/v1/tasks/{task_id}/legacy-result")
    async def get_legacy_result(
        request: Request,
        task_id: str,
        file_name: Annotated[str, Query(min_length=1)],
    ) -> dict[str, object]:
        task = await request.app.state.container.storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        record = await request.app.state.container.storage.get_result(task_id, file_name)
        if record is None:
            raise HTTPException(status_code=404, detail="Review result not found")
        return record.review.model_dump(mode="json")

    @app.post("/api/v1/knowledge/reload")
    async def reload_knowledge(request: Request) -> dict[str, str]:
        request.app.state.container.knowledge.reload()
        return {"status": "reloaded"}

    return app
