from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.repositories import router as repositories_router

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)

app = FastAPI(title="DevPilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

app.include_router(repositories_router, prefix="/api")


@app.exception_handler(RequestValidationError)
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
