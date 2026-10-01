"""FastAPI application factory.

Route layout follows the requested API surface while reusing existing routers
(``/api`` prefix on every route).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.core.errors import AppError, classify
from backend.app.core.events import bus
from backend.app.core.observability import configure_logging, get_logger
from backend.app.middleware import RateLimitMiddleware, RequestContextMiddleware
from backend.app.routers import agent as agent_router
from backend.app.routers import models as models_router
from backend.app.routers import projects as projects_router
from backend.app.routers import system as system_router
from configs.settings import settings

logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    configure_logging(settings.log_level)
    settings.ensure_dirs()

    from database.migrations import init_db

    new_migrations = init_db()
    logger.info("database ready (migrations applied: %s)", new_migrations or "none")

    from tools.registry import registry as tool_registry

    tool_registry.load_builtin_tools()

    from models.registry import registry as model_registry

    try:
        model_registry.refresh(force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("model probe failed at startup: %s", exc)

    # Bind the event bus to the running loop for thread-safe SSE delivery.
    try:
        bus.bind_loop(asyncio.get_running_loop())
    except RuntimeError:  # pragma: no cover
        pass

    if settings.environment != "production":
        from database.seed import seed_demo

        try:
            seed_demo()
        except Exception as exc:  # noqa: BLE001
            logger.debug("demo seed skipped: %s", exc)

    logger.info("%s v%s ready", settings.app_name, settings.app_version)
    yield
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="LocalAI Workspace — an independent, local AI workspace with a Super Agent orchestrator.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "x-process-time-ms"],
    )

    # ------------------------------------------------------------- errors
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):  # noqa: ANN202
        status_map = {
            "UserError": 400,
            "ValidationError": 422,
            "PermissionError": 403,
            "ModelUnavailable": 503,
            "NetworkError": 502,
            "ToolError": 400,
            "InternalError": 500,
        }
        return JSONResponse(status_code=status_map.get(exc.error_class.value, 500), content=exc.to_dict())

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN202
        app_err = classify(exc)
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content=app_err.to_dict())

    # ------------------------------------------------------------ routers
    # Models/Providers router is registered first so its richer /models surface
    # takes precedence over the legacy one.
    app.include_router(models_router.router, prefix="/api")
    app.include_router(system_router.router, prefix="/api")
    app.include_router(projects_router.router, prefix="/api")
    app.include_router(agent_router.router, prefix="/api")

    # Serve the built frontend (Next.js static export) when present.
    try:
        from pathlib import Path

        web_candidates = [Path(settings.repo_root) / "frontend" / "out", Path(settings.repo_root) / "frontend" / "dist"]
        for candidate in web_candidates:
            if candidate.is_dir() and any(candidate.iterdir()):
                app.mount("/", StaticFiles(directory=str(candidate), html=True), name="frontend")
                logger.info("serving frontend from %s", candidate)
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("frontend mount skipped: %s", exc)

    return app


app = create_app()


__all__ = ["app", "create_app"]
