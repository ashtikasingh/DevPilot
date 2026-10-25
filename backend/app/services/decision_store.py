import json
from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Decision
from app.schemas.decision import DecisionCreate, DecisionResponse, DecisionUpdate


QA_MEMORY_MAX_DECISIONS = 5
QA_MEMORY_MAX_CONTEXT_BYTES = 8 * 1024


def relevant_decisions_for_qa(
    session: Session,
    owner_key: str,
    repository_key: str,
    source_paths: set[str],
) -> list[dict[str, str | None]]:
    """Return bounded same-repository decisions relevant to the supplied files."""
    with session.begin():
        scoped = (
            select(Decision)
            .where(
                Decision.owner_key == owner_key,
                Decision.repository_key == repository_key,
            )
            .order_by(Decision.updated_at.desc(), Decision.id)
        )
        path_rows = []
        if source_paths:
            path_rows = session.scalars(
                scoped.where(Decision.source_path.in_(sorted(source_paths))).limit(
                    QA_MEMORY_MAX_DECISIONS
                )
            ).all()

        repository_wide_rows = session.scalars(
            scoped.where(Decision.source_path.is_(None)).limit(QA_MEMORY_MAX_DECISIONS)
        ).all()

        other_paths_query = scoped.where(Decision.source_path.is_not(None))
        if source_paths:
            other_paths_query = other_paths_query.where(
                Decision.source_path.not_in(sorted(source_paths))
            )
        other_path_rows = session.scalars(
            other_paths_query.limit(QA_MEMORY_MAX_DECISIONS)
        ).all()

        bounded: list[dict[str, str | None]] = []
        for decision in [*path_rows, *repository_wide_rows, *other_path_rows]:
            if len(bounded) >= QA_MEMORY_MAX_DECISIONS:
                break
            item = {
                "title": decision.title,
                "source_path": decision.source_path,
                "content": decision.content,
            }
            candidate = bounded + [item]
            candidate_bytes = len(
                json.dumps(candidate, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            )
            if candidate_bytes <= QA_MEMORY_MAX_CONTEXT_BYTES:
                bounded.append(item)
        return bounded


def _response(decision: Decision, canonical_repository: str) -> DecisionResponse:
    created_at = decision.created_at
    updated_at = decision.updated_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return DecisionResponse(
        id=UUID(decision.id),
        repository=canonical_repository,
        title=decision.title,
        content=decision.content,
        source_path=decision.source_path,
        created_at=created_at,
        updated_at=updated_at,
    )


def list_decisions(
    session: Session,
    owner_key: str,
    repository_key: str,
    canonical_repository: str,
    limit: int,
    offset: int,
) -> list[DecisionResponse]:
    with session.begin():
        rows = session.scalars(
            select(Decision)
            .where(
                Decision.owner_key == owner_key,
                Decision.repository_key == repository_key,
            )
            .order_by(Decision.updated_at.desc(), Decision.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return [_response(row, canonical_repository) for row in rows]


def create_decision(
    session: Session,
    owner_key: str,
    repository_key: str,
    canonical_repository: str,
    payload: DecisionCreate,
) -> DecisionResponse:
    with session.begin():
        decision = Decision(
            owner_key=owner_key,
            repository_key=repository_key,
            title=payload.title,
            content=payload.content,
            source_path=payload.source_path,
        )
        session.add(decision)
        session.flush()
        return _response(decision, canonical_repository)


def update_decision(
    session: Session,
    owner_key: str,
    repository_key: str,
    canonical_repository: str,
    decision_id: UUID,
    payload: DecisionUpdate,
) -> DecisionResponse | None:
    with session.begin():
        decision = session.scalar(
            select(Decision).where(
                Decision.id == str(decision_id),
                Decision.owner_key == owner_key,
                Decision.repository_key == repository_key,
            )
        )
        if decision is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(decision, field, value)
        session.flush()
        return _response(decision, canonical_repository)


def delete_decision(
    session: Session,
    owner_key: str,
    repository_key: str,
    decision_id: UUID,
) -> bool:
    with session.begin():
        decision = session.scalar(
            select(Decision).where(
                Decision.id == str(decision_id),
                Decision.owner_key == owner_key,
                Decision.repository_key == repository_key,
            )
        )
        if decision is None:
            return False
        session.delete(decision)
        return True
