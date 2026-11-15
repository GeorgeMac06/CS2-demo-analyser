"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from cs2scout import __version__
from cs2scout.settings import Settings
from cs2scout.web.security import LocalGuard


def create_app(settings: Settings, token: str) -> FastAPI:
    # Interactive docs and the OpenAPI schema are disabled: they would be an
    # unauthenticated API surface outside /api/*.
    app = FastAPI(title="CS2 Demo Scout", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.token = token

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "workspace": str(settings.home)}

    app.add_middleware(LocalGuard, port=settings.port, token=token)
    return app
