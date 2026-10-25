from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas.repository import (
    InspectRepositoryRequest,
    InspectRepositoryResponse,
    RepositoryFileRequest,
    RepositoryFileResponse,
    RepositoryQuestionRequest,
    RepositoryQuestionResponse,
    RelatedRepositoryQuestionResponse,
    RelatedSource,
)
from app.database import get_db
from app.services.code_context import build_related_context
from app.services.decision_store import relevant_decisions_for_qa
from app.services.github import (
    GitHubAPIError,
    InvalidRepositoryURL,
    inspect_public_repository,
    fetch_public_file_content,
)
from app.services.gemini import (
    GeminiAPIError,
    answer_about_source,
    answer_about_sources,
    validate_gemini_configuration,
)
from app.services.rate_limit import qa_rate_limit_settings, qa_request_limiter

router = APIRouter(tags=["repositories"])


def _qa_memory_context(
    session: Session,
    repository: str,
    source_paths: set[str],
) -> list[dict[str, str | None]]:
    """Load only bounded decisions for the successfully retrieved repository."""
    if repository.count("/") != 1:
        return []
    owner, name = repository.split("/", 1)
    if not owner or not name:
        return []
    try:
        return relevant_decisions_for_qa(
            session,
            owner.lower(),
            name.lower(),
            source_paths,
        )
    except SQLAlchemyError:
        # Memory is optional context. A failed read must not block code Q&A.
        try:
            session.rollback()
        except SQLAlchemyError:
            pass
        return []


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


def _qa_rate_limit_response(request: Request) -> JSONResponse | None:
    limit, window_seconds = qa_rate_limit_settings()
    client_host = request.client.host if request.client is not None else "unknown"
    retry_after = qa_request_limiter.consume(
        client_host[:128], limit, window_seconds
    )
    if retry_after is None:
        return None
    return _error_response(
        429,
        "qa_rate_limited",
        "Too many Q&A requests. Wait briefly, then try again.",
        retry_after,
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
        429: {"description": "GitHub or Q&A rate limit reached"},
        502: {"description": "GitHub or Gemini API error"},
        503: {"description": "Gemini is not configured or unavailable"},
        504: {"description": "GitHub or Gemini API timeout"},
    },
)
async def ask_about_repository_file(
    request: RepositoryQuestionRequest,
    http_request: Request,
    session: Session = Depends(get_db),
) -> RepositoryQuestionResponse | JSONResponse:
    question = request.question.strip()
    if not question:
        return _error_response(422, "invalid_question", "Enter a question about this file.")
    rate_limit_response = _qa_rate_limit_response(http_request)
    if rate_limit_response is not None:
        return rate_limit_response

    try:
        validate_gemini_configuration()
        repository, path, _ref, content, _size_bytes = await fetch_public_file_content(
            request.owner,
            request.repository,
            request.path,
            request.ref,
        )
        memory_context = _qa_memory_context(session, repository, {path})
        answer = await answer_about_source(
            repository, path, content, question, memory_context=memory_context
        )
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


@router.post(
    "/repositories/ask-related",
    response_model=RelatedRepositoryQuestionResponse,
    responses={
        404: {"description": "Repository or file is missing or not public"},
        413: {"description": "Selected source file exceeds the supported size"},
        415: {"description": "Selected file is not supported text"},
        429: {"description": "GitHub or Q&A rate limit reached"},
        502: {"description": "GitHub or Gemini API error"},
        503: {"description": "Gemini is not configured or unavailable"},
        504: {"description": "GitHub or Gemini API timeout"},
    },
)
async def ask_about_related_files(
    request: RepositoryQuestionRequest,
    http_request: Request,
    session: Session = Depends(get_db),
) -> RelatedRepositoryQuestionResponse | JSONResponse:
    question = request.question.strip()
    if not question:
        return _error_response(422, "invalid_question", "Enter a question about these files.")
    rate_limit_response = _qa_rate_limit_response(http_request)
    if rate_limit_response is not None:
        return rate_limit_response

    try:
        validate_gemini_configuration()
        # Related context retrieval fetches the selected file itself so that its
        # content, tree ref, and all budget checks share one bounded operation.
        context = await build_related_context(
            request.owner,
            request.repository,
            request.path,
            request.ref,
        )
        repository = f"{request.owner}/{request.repository}"
        memory_context = _qa_memory_context(
            session,
            repository,
            {source.path for source in context.sources},
        )
        answer = await answer_about_sources(
            repository,
            [(source.source_id, source.path, source.content) for source in context.sources],
            question,
            memory_context=memory_context,
        )
        selected = context.sources[0]
        return RelatedRepositoryQuestionResponse(
            repository=repository,
            path=selected.path,
            answer=answer,
            sources=[
                RelatedSource(
                    source_id=source.source_id,
                    path=source.path,
                    size_bytes=source.size_bytes,
                )
                for source in context.sources
            ],
            context_complete=context.complete,
            context_message=context.message,
        )
    except GitHubAPIError as error:
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            error.retry_after_seconds,
        )
    except GeminiAPIError as error:
        return _error_response(error.status_code, error.code, error.message)
