from contextlib import asynccontextmanager
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.decisions import router as decisions_router
from app.api.repositories import router as repositories_router
from app.database import create_database, initialize_database

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)


DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def parse_cors_origins(value: str | None) -> list[str]:
    """Parse an exact origin allowlist; wildcard origins are never accepted."""
    if value is None or not value.strip():
        return list(DEFAULT_CORS_ORIGINS)

    origins: list[str] = []
    for item in value.split(","):
        origin = item.strip()
        if not origin:
            continue
        if "*" in origin:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit origins, not wildcards")

        parsed = urlsplit(origin)
        try:
            _ = parsed.port
        except ValueError as error:
            raise ValueError("CORS_ALLOWED_ORIGINS contains an invalid origin") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORS_ALLOWED_ORIGINS contains an invalid origin")

        normalized = f"{parsed.scheme}://{parsed.netloc}"
        if normalized not in origins:
            origins.append(normalized)

    return origins or list(DEFAULT_CORS_ORIGINS)


def create_app(
    cors_origins: list[str] | None = None,
    database_url: str | None = None,
) -> FastAPI:
    database = create_database(database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            initialize_database(database)
            yield
        finally:
            database.engine.dispose()

    application = FastAPI(title="DevPilot API", version="0.1.0", lifespan=lifespan)
    application.state.database = database

    application.add_middleware(
        CORSMiddleware,
        allow_origins=(
            parse_cors_origins(os.environ.get("CORS_ALLOWED_ORIGINS"))
            if cors_origins is None
            else cors_origins
        ),
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    application.include_router(repositories_router, prefix="/api")
    application.include_router(decisions_router, prefix="/api")

    @application.get("/healthz", include_in_schema=False)
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @application.exception_handler(RequestValidationError)
    async def handle_invalid_request(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "The request is invalid. Check the required fields and their length limits.",
                }
            },
        )

    return application


app = create_app()
