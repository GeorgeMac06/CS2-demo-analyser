"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cs2scout import __version__
from cs2scout.jobs.runner import JobRunner
from cs2scout.settings import Settings
from cs2scout.store.library import Library
from cs2scout.web import api, errors, pages
from cs2scout.web.security import LocalGuard

log = logging.getLogger(__name__)


def create_app(settings: Settings, token: str) -> FastAPI:
    library = Library(settings.home)
    report = library.startup_cleanup()
    if any(report.values()):
        log.warning("cleaned up after an interrupted run: %s", report)
    runner = JobRunner(library)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        runner.shutdown()

    # Interactive docs and the OpenAPI schema are disabled: they would be an
    # unauthenticated API surface outside /api/*.
    app = FastAPI(
        title="CS2 Demo Scout", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.token = token
    app.state.library = library
    app.state.runner = runner
    errors.install(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "workspace": str(settings.home)}

    app.include_router(api.router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.add_middleware(LocalGuard, port=settings.port, token=token)
    return app
