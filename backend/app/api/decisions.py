import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.decision import (
    DecisionCreate,
    DecisionListResponse,
    DecisionResponse,
    DecisionUpdate,
)
from app.services.decision_store import (
    create_decision,
    delete_decision,
    list_decisions,
    update_decision,
)
from app.services.github import GitHubAPIError, verify_public_repository
from app.services.rate_limit import (
    DECISION_WRITE_RATE_LIMIT,
    DECISION_WRITE_RATE_WINDOW_SECONDS,
    decision_write_limiter,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["developer memory"])


def _error_response(
    status_code: int,
    code: str,
    message: str,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    headers = {}
    error: dict[str, str | int] = {"code": code, "message": message}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(retry_after_seconds)
        error["retry_after_seconds"] = retry_after_seconds
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


def _write_rate_limit(request: Request) -> JSONResponse | None:
    client_host = request.client.host if request.client is not None else "unknown"
    retry_after = decision_write_limiter.consume(
        client_host[:128],
        DECISION_WRITE_RATE_LIMIT,
        DECISION_WRITE_RATE_WINDOW_SECONDS,
    )
    if retry_after is None:
        return None
    return _error_response(
        429,
        "decision_write_rate_limited",
        "Too many memory changes. Wait briefly, then try again.",
        retry_after,
    )


def _database_error(operation: str, error: SQLAlchemyError) -> JSONResponse:
    # Do not log exception text: SQLAlchemy messages may contain SQL or values.
    logger.warning(
        "developer_memory_database_failure operation=%s exception_type=%s",
        operation,
        type(error).__name__,
    )
    return _error_response(
        503,
        "memory_unavailable",
        "Developer Memory is temporarily unavailable. Try again shortly.",
    )


def _repository_error(error: GitHubAPIError) -> JSONResponse:
    return _error_response(
        error.status_code,
        error.code,
        error.message,
        error.retry_after_seconds,
    )


@router.get(
    "/repositories/{owner}/{repository}/decisions",
    response_model=DecisionListResponse,
    responses={404: {"description": "Repository is missing or not public"}},
)
async def get_decisions(
    owner: str,
    repository: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    session: Session = Depends(get_db),
) -> DecisionListResponse | JSONResponse:
    try:
        canonical_owner, canonical_repository = await verify_public_repository(owner, repository)
    except GitHubAPIError as error:
        return _repository_error(error)

    display_repository = f"{canonical_owner}/{canonical_repository}"
    try:
        decisions = list_decisions(
            session,
            canonical_owner.lower(),
            canonical_repository.lower(),
            display_repository,
            limit,
            offset,
        )
        return DecisionListResponse(
            repository=display_repository,
            decisions=decisions,
            limit=limit,
            offset=offset,
        )
    except SQLAlchemyError as error:
        return _database_error("list", error)


@router.post(
    "/repositories/{owner}/{repository}/decisions",
    response_model=DecisionResponse,
    status_code=201,
    responses={404: {"description": "Repository is missing or not public"}, 429: {"description": "Write rate limit reached"}},
)
async def create_decision_for_repository(
    owner: str,
    repository: str,
    payload: DecisionCreate,
    request: Request,
    session: Session = Depends(get_db),
) -> DecisionResponse | JSONResponse:
    limited = _write_rate_limit(request)
    if limited is not None:
        return limited
    try:
        canonical_owner, canonical_repository = await verify_public_repository(owner, repository)
    except GitHubAPIError as error:
        return _repository_error(error)

    try:
        return create_decision(
            session,
            canonical_owner.lower(),
            canonical_repository.lower(),
            f"{canonical_owner}/{canonical_repository}",
            payload,
        )
    except SQLAlchemyError as error:
        return _database_error("create", error)


@router.patch(
    "/repositories/{owner}/{repository}/decisions/{decision_id}",
    response_model=DecisionResponse,
    responses={404: {"description": "Repository or decision not found"}, 429: {"description": "Write rate limit reached"}},
)
async def patch_decision(
    owner: str,
    repository: str,
    decision_id: UUID,
    payload: DecisionUpdate,
    request: Request,
    session: Session = Depends(get_db),
) -> DecisionResponse | JSONResponse:
    limited = _write_rate_limit(request)
    if limited is not None:
        return limited
    try:
        canonical_owner, canonical_repository = await verify_public_repository(owner, repository)
    except GitHubAPIError as error:
        return _repository_error(error)

    try:
        decision = update_decision(
            session,
            canonical_owner.lower(),
            canonical_repository.lower(),
            f"{canonical_owner}/{canonical_repository}",
            decision_id,
            payload,
        )
        if decision is None:
            return _error_response(404, "decision_not_found", "Decision was not found for this repository.")
        return decision
    except SQLAlchemyError as error:
        return _database_error("update", error)


@router.delete(
    "/repositories/{owner}/{repository}/decisions/{decision_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
    responses={404: {"description": "Repository or decision not found"}, 429: {"description": "Write rate limit reached"}},
)
async def remove_decision(
    owner: str,
    repository: str,
    decision_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
) -> Response:
    limited = _write_rate_limit(request)
    if limited is not None:
        return limited
    try:
        canonical_owner, canonical_repository = await verify_public_repository(owner, repository)
    except GitHubAPIError as error:
        return _repository_error(error)

    try:
        deleted = delete_decision(
            session,
            canonical_owner.lower(),
            canonical_repository.lower(),
            decision_id,
        )
        if not deleted:
            return _error_response(404, "decision_not_found", "Decision was not found for this repository.")
        return Response(status_code=204)
    except SQLAlchemyError as error:
        return _database_error("delete", error)
