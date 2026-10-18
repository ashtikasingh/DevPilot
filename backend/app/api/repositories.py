from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.repository import (
    InspectRepositoryRequest,
    InspectRepositoryResponse,
    RepositoryFileRequest,
    RepositoryFileResponse,
    RepositoryQuestionRequest,
    RepositoryQuestionResponse,
)
from app.services.github import (
    GitHubAPIError,
    InvalidRepositoryURL,
    inspect_public_repository,
    fetch_public_file_content,
)
from app.services.gemini import (
    GeminiAPIError,
    answer_about_source,
    validate_gemini_configuration,
)

router = APIRouter(tags=["repositories"])


def _error_response(
    status_code: int,
    code: str,
    message: str,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    headers = {}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(retry_after_seconds)

    error: dict[str, str | int] = {"code": code, "message": message}
    if retry_after_seconds is not None:
        error["retry_after_seconds"] = retry_after_seconds

    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=headers,
    )


@router.post(
    "/repositories/inspect",
    response_model=InspectRepositoryResponse,
    responses={
        422: {"description": "Invalid GitHub repository URL"},
        404: {"description": "Repository is missing or not public"},
        429: {"description": "GitHub rate limit reached"},
        502: {"description": "GitHub API error"},
        504: {"description": "GitHub API timeout"},
    },
)
async def inspect_repository(
    request: InspectRepositoryRequest,
) -> InspectRepositoryResponse | JSONResponse:
    try:
        return await inspect_public_repository(request.repository_url)
    except InvalidRepositoryURL:
        return _error_response(
            422,
            "invalid_repository_url",
            "Enter a public repository URL in the form https://github.com/owner/repository.",
        )
    except GitHubAPIError as error:
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            error.retry_after_seconds,
        )


@router.post(
    "/repositories/file",
    response_model=RepositoryFileResponse,
    responses={
        404: {"description": "Repository or file is missing or not public"},
        413: {"description": "Source file exceeds the supported size"},
        415: {"description": "File is not supported text"},
        429: {"description": "GitHub rate limit reached"},
        502: {"description": "GitHub API error"},
        504: {"description": "GitHub API timeout"},
    },
)
async def get_repository_file(
    request: RepositoryFileRequest,
) -> RepositoryFileResponse | JSONResponse:
    try:
        repository, path, ref, content, size_bytes = await fetch_public_file_content(
            request.owner,
            request.repository,
            request.path,
            request.ref,
        )
        return RepositoryFileResponse(
            repository=repository,
            path=path,
            ref=ref,
            content=content,
            size_bytes=size_bytes,
        )
    except GitHubAPIError as error:
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            error.retry_after_seconds,
        )


@router.post(
    "/repositories/ask",
    response_model=RepositoryQuestionResponse,
    responses={
        404: {"description": "Repository or file is missing or not public"},
        413: {"description": "Source file exceeds the supported size"},
        415: {"description": "File is not supported text"},
        429: {"description": "GitHub rate limit reached"},
        502: {"description": "GitHub or Gemini API error"},
        503: {"description": "Gemini is not configured or unavailable"},
        504: {"description": "GitHub or Gemini API timeout"},
    },
)
async def ask_about_repository_file(
    request: RepositoryQuestionRequest,
) -> RepositoryQuestionResponse | JSONResponse:
    question = request.question.strip()
    if not question:
        return _error_response(422, "invalid_question", "Enter a question about this file.")

    try:
        validate_gemini_configuration()
        repository, path, _ref, content, _size_bytes = await fetch_public_file_content(
            request.owner,
            request.repository,
            request.path,
            request.ref,
        )
        answer = await answer_about_source(repository, path, content, question)
        return RepositoryQuestionResponse(repository=repository, path=path, answer=answer)
    except GitHubAPIError as error:
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            error.retry_after_seconds,
        )
    except GeminiAPIError as error:
        return _error_response(error.status_code, error.code, error.message)
