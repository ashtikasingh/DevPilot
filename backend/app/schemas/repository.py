from typing import Literal

from pydantic import BaseModel, Field


class InspectRepositoryRequest(BaseModel):
    repository_url: str = Field(min_length=1, max_length=2048)


class RepositoryMetadata(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    default_branch: str
    stargazers_count: int = 0


class RepositoryTreeEntry(BaseModel):
    path: str
    type: Literal["blob", "tree", "commit"]
    sha: str
    size: int | None = None


class InspectRepositoryResponse(BaseModel):
    repository: RepositoryMetadata
    tree: list[RepositoryTreeEntry]
    tree_complete: bool
    tree_truncated: bool
    tree_message: str | None = None


class RepositoryFileRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=39)
    repository: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=1024)
    ref: str | None = Field(default=None, min_length=1, max_length=255)


class RepositoryFileResponse(BaseModel):
    repository: str
    path: str
    ref: str
    content: str
    size_bytes: int


class RepositoryQuestionRequest(RepositoryFileRequest):
    question: str = Field(min_length=1, max_length=2000)


class RepositoryQuestionResponse(BaseModel):
    repository: str
    path: str
    answer: str
