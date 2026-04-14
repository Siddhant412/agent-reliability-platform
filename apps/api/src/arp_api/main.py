from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from arp_api.routes.health import router as health_router
from arp_api.routes.organizations import router as organizations_router
from arp_api.routes.projects import router as projects_router
from arp_api.routes.runs import router as runs_router
from arp_api.routes.workflows import router as workflows_router
from arp_api.settings import APISettings, get_settings
from arp_core.application.exceptions import ApplicationError, ConflictError, NotFoundError
from arp_core.persistence.session import SessionManager


def create_app(*, database_url: str | None = None) -> FastAPI:
    settings = APISettings(database_url=database_url) if database_url is not None else get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.session_manager = SessionManager(settings.database_url)

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def handle_conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ApplicationError)
    async def handle_application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(health_router)
    app.include_router(organizations_router)
    app.include_router(projects_router)
    app.include_router(workflows_router)
    app.include_router(runs_router)
    return app


app = create_app()
