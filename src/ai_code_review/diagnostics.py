from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ai_code_review.config import Settings


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def build_config_report(
    settings: Settings,
    *,
    deployment: str,
) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []

    if deployment not in {"docker", "native"}:
        raise ValueError("deployment must be 'docker' or 'native'")

    base_url = settings.anthropic_base_url
    parsed = urlparse(base_url) if base_url else None
    if not (
        settings.anthropic_api_key
        or settings.anthropic_auth_token
        or base_url
    ):
        errors.append(
            "Model API is not configured. Set ANTHROPIC_BASE_URL and, "
            "when required, ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN."
        )
    if settings.anthropic_api_key and settings.anthropic_auth_token:
        warnings.append(
            "Both ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are set; "
            "normally only one authentication method should be configured."
        )
    if parsed and deployment == "docker" and parsed.hostname in LOOPBACK_HOSTS:
        errors.append(
            "ANTHROPIC_BASE_URL points to container loopback. On Linux Docker, "
            "use host.docker.internal for a gateway running on the Docker host."
        )
    if parsed and deployment == "native" and parsed.hostname == "host.docker.internal":
        warnings.append(
            "host.docker.internal is intended for containers. For native Linux, "
            "use 127.0.0.1 or the gateway's actual intranet address."
        )
    if parsed and parsed.path.rstrip("/").endswith("/v1/messages"):
        warnings.append(
            "ANTHROPIC_BASE_URL normally should be the gateway base URL, "
            "not the complete /v1/messages endpoint."
        )

    if not settings.service_api_key:
        warnings.append(
            "SERVICE_API_KEY is empty; review task and result APIs are unauthenticated."
        )
    if not settings.allowed_local_repo_roots:
        warnings.append(
            "ALLOWED_LOCAL_REPO_ROOTS is empty; local_path review tasks are disabled."
        )
    if "*" in settings.allowed_repo_hosts:
        warnings.append(
            "ALLOWED_REPO_HOSTS contains '*'; remote repository host filtering is disabled."
        )

    auth_mode = "none"
    if settings.anthropic_api_key:
        auth_mode = "api_key"
    elif settings.anthropic_auth_token:
        auth_mode = "bearer_token"

    return {
        "status": "error" if errors else "ok",
        "deployment": deployment,
        "model": {
            "base_url": base_url or "https://api.anthropic.com",
            "model": settings.claude_model,
            "auth_mode": auth_mode,
            "effort": settings.claude_effort,
            "timeout_seconds": settings.claude_timeout_seconds,
            "max_turns": settings.claude_max_turns,
        },
        "mongodb": {
            "database": settings.mongodb_database,
            "uri": _mask_mongodb_uri(settings.mongodb_uri),
        },
        "paths": {
            "workspace_root": str(settings.workspace_root),
            "knowledge_root": str(settings.knowledge_root),
            "allowed_local_repo_roots": [
                str(path) for path in settings.allowed_local_repo_roots
            ],
        },
        "remote_repository_hosts": settings.allowed_repo_hosts,
        "api": {
            "host": settings.api_host,
            "port": settings.api_port,
            "authentication_enabled": bool(settings.service_api_key),
        },
        "errors": errors,
        "warnings": warnings,
    }


def _mask_mongodb_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if not parsed.username and not parsed.password:
        return uri
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    credentials = "***"
    if parsed.username:
        credentials = f"{parsed.username}:***"
    return parsed._replace(netloc=f"{credentials}@{host}").geturl()


def validate_config_paths(settings: Settings) -> list[str]:
    warnings: list[str] = []
    for label, path in (
        ("WORKSPACE_ROOT", settings.workspace_root),
        ("KNOWLEDGE_ROOT", settings.knowledge_root),
    ):
        if not Path(path).exists():
            warnings.append(f"{label} does not exist yet: {path}")
    for path in settings.allowed_local_repo_roots:
        if not path.is_dir():
            warnings.append(f"Allowed local repository root does not exist: {path}")
    return warnings
