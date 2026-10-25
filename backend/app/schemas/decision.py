from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_source_path(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not value.strip()
        or len(value) > 1024
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Enter a safe repository-relative source path.")
    return value


class DecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=4000)
    source_path: str | None = Field(default=None, max_length=1024)

    @field_validator("title", "content")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value

    @field_validator("source_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        return _validate_source_path(value)


class DecisionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    source_path: str | None = Field(default=None, max_length=1024)

    @field_validator("title", "content")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value

    @field_validator("source_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        return _validate_source_path(value)

    @model_validator(mode="after")
    def require_update_fields(self) -> "DecisionUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("title", "content")
        ):
            raise ValueError("Title and content cannot be null.")
        return self


class DecisionResponse(BaseModel):
    id: UUID
    repository: str
    title: str
    content: str
    source_path: str | None
    created_at: datetime
    updated_at: datetime


class DecisionListResponse(BaseModel):
    repository: str
    decisions: list[DecisionResponse]
    limit: int
    offset: int
