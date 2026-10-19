import re
import time
import base64
import binascii
from urllib.parse import quote, unquote, urlsplit

import httpx
from pydantic import ValidationError

from app.schemas.repository import (
    InspectRepositoryResponse,
    RepositoryMetadata,
    RepositoryTreeEntry,
)

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
REQUEST_TIMEOUT_SECONDS = 12.0
MAX_SOURCE_FILE_BYTES = 128 * 1024


class InvalidRepositoryURL(Exception):
    """The submitted URL does not identify a GitHub repository."""


class GitHubAPIError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def parse_repository_url(repository_url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(repository_url.strip())
        port = parsed.port
    except ValueError as error:
        raise InvalidRepositoryURL from error

    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidRepositoryURL

    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if len(parts) != 2:
        raise InvalidRepositoryURL

    owner, repository = parts
    if repository.lower().endswith(".git"):
        repository = repository[:-4]

    if (
        not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repository)
        or repository in {".", ".."}
    ):
        raise InvalidRepositoryURL

    return owner, repository


def _rate_limit_delay(response: httpx.Response) -> int | None:
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return max(1, int(retry_after))

    reset_at = response.headers.get("X-RateLimit-Reset")
    if reset_at and reset_at.isdigit():
        return max(1, int(reset_at) - int(time.time()))

    return None


def _raise_for_github_error(
    response: httpx.Response,
    not_found_message: str = "Repository was not found or is not public. Check the URL and repository visibility.",
) -> None:
    if response.is_success:
        return

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    upstream_message = payload.get("message", "") if isinstance(payload, dict) else ""
    remaining = response.headers.get("X-RateLimit-Remaining")
    is_rate_limited = (
        response.status_code == 429
        or remaining == "0"
        or "rate limit" in str(upstream_message).lower()
        or response.headers.get("Retry-After") is not None
    )

    if is_rate_limited:
        raise GitHubAPIError(
            "github_rate_limited",
            "GitHub's public API rate limit has been reached. Try again after the indicated wait.",
            429,
            _rate_limit_delay(response),
        )

    if response.status_code == 404:
        raise GitHubAPIError(
            "repository_not_found",
            not_found_message,
            404,
        )

    if response.status_code in (401, 403):
        raise GitHubAPIError(
            "github_access_denied",
            "GitHub could not provide this public repository. Check that it is public and try again.",
            502,
        )

    raise GitHubAPIError(
        "github_api_error",
        "GitHub could not return this repository right now. Try again shortly.",
        502,
    )


async def inspect_public_repository(repository_url: str) -> InspectRepositoryResponse:
    owner, repository = parse_repository_url(repository_url)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "DevPilot-Repository-Inspector",
    }

    try:
        async with httpx.AsyncClient(
            base_url=GITHUB_API,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as client:
            metadata_response = await client.get(f"/repos/{owner}/{repository}")
            _raise_for_github_error(metadata_response)
            metadata_payload = metadata_response.json()

            if not isinstance(metadata_payload, dict) or metadata_payload.get("private") is True:
                raise GitHubAPIError(
                    "repository_not_found",
                    "Repository was not found or is not public. Check the URL and repository visibility.",
                    404,
                )

            metadata = RepositoryMetadata.model_validate(metadata_payload)
            encoded_branch = quote(metadata.default_branch, safe="")
            tree_response = await client.get(
                f"/repos/{owner}/{repository}/git/trees/{encoded_branch}",
                params={"recursive": "1"},
            )
            _raise_for_github_error(tree_response)
            tree_payload = tree_response.json()

        if not isinstance(tree_payload, dict) or not isinstance(tree_payload.get("tree"), list):
            raise GitHubAPIError(
                "github_api_error",
                "GitHub returned an unexpected repository tree. Try again shortly.",
                502,
            )

        entries = [RepositoryTreeEntry.model_validate(entry) for entry in tree_payload["tree"]]
        truncated = tree_payload.get("truncated") is True

        return InspectRepositoryResponse(
            repository=metadata,
            tree=entries,
            tree_complete=not truncated,
            tree_truncated=truncated,
            tree_message=(
                "GitHub truncated this recursive tree. The entries shown may be incomplete."
                if truncated
                else None
            ),
        )
    except httpx.TimeoutException as error:
        raise GitHubAPIError(
            "github_timeout",
            "GitHub took too long to respond. Try again shortly.",
            504,
        ) from error
    except httpx.RequestError as error:
        raise GitHubAPIError(
            "github_unavailable",
            "DevPilot could not reach GitHub. Check your connection and try again.",
            502,
        ) from error
    except (ValueError, ValidationError) as error:
        raise GitHubAPIError(
            "github_api_error",
            "GitHub returned an unexpected response. Try again shortly.",
            502,
        ) from error


async def fetch_public_repository_tree(
    owner: str,
    repository: str,
    ref: str,
) -> tuple[list[RepositoryTreeEntry], bool]:
    _validate_file_reference(owner, repository, "tree")
    if not isinstance(ref, str) or not ref or len(ref) > 255:
        raise GitHubAPIError(
            "invalid_file_reference",
            "The repository branch could not be resolved. Inspect the repository again.",
            422,
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "DevPilot-Repository-Inspector",
    }
    try:
        async with httpx.AsyncClient(
            base_url=GITHUB_API,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                f"/repos/{owner}/{repository}/git/trees/{quote(ref, safe='')}",
                params={"recursive": "1"},
            )
            _raise_for_github_error(response)
            payload = response.json()

        if not isinstance(payload, dict) or not isinstance(payload.get("tree"), list):
            raise GitHubAPIError(
                "github_api_error",
                "GitHub returned an unexpected repository tree. Try again shortly.",
                502,
            )
        entries = [RepositoryTreeEntry.model_validate(entry) for entry in payload["tree"]]
        return entries, payload.get("truncated") is True
    except httpx.TimeoutException as error:
        raise GitHubAPIError(
            "github_timeout",
            "GitHub took too long to return the repository tree. Try again shortly.",
            504,
        ) from error
    except httpx.RequestError as error:
        raise GitHubAPIError(
            "github_unavailable",
            "DevPilot could not reach GitHub. Check your connection and try again.",
            502,
        ) from error
    except (ValueError, ValidationError) as error:
        raise GitHubAPIError(
            "github_api_error",
            "GitHub returned an unexpected repository tree. Try again shortly.",
            502,
        ) from error


def _validate_file_reference(owner: str, repository: str, path: str) -> None:
    if (
        not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repository)
        or repository in {".", ".."}
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise GitHubAPIError(
            "invalid_file_reference",
            "Choose a file from the inspected repository tree.",
            422,
        )


async def fetch_public_file_content(
    owner: str,
    repository: str,
    path: str,
    ref: str | None = None,
) -> tuple[str, str, str, str, int]:
    _validate_file_reference(owner, repository, path)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "DevPilot-Repository-Inspector",
    }

    try:
        async with httpx.AsyncClient(
            base_url=GITHUB_API,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as client:
            if ref is None:
                metadata_response = await client.get(f"/repos/{owner}/{repository}")
                _raise_for_github_error(metadata_response)
                metadata_payload = metadata_response.json()
                if not isinstance(metadata_payload, dict) or metadata_payload.get("private") is True:
                    raise GitHubAPIError(
                        "repository_not_found",
                        "Repository was not found or is not public. Check its visibility.",
                        404,
                    )
                ref = metadata_payload.get("default_branch")
            if not isinstance(ref, str) or not ref or len(ref) > 255:
                raise GitHubAPIError(
                    "invalid_file_reference",
                    "The repository branch could not be resolved. Inspect the repository again.",
                    422,
                )

            encoded_path = quote(path, safe="/")
            response = await client.get(
                f"/repos/{owner}/{repository}/contents/{encoded_path}",
                params={"ref": ref},
            )
            _raise_for_github_error(
                response,
                "File or public repository was not found. Choose a file from the current repository tree.",
            )
            payload = response.json()

        if not isinstance(payload, dict) or payload.get("type") != "file":
            raise GitHubAPIError(
                "unsupported_file",
                "Select a regular text source file. Directories and submodules are not supported.",
                415,
            )

        size = payload.get("size")
        if not isinstance(size, int) or size < 0:
            raise GitHubAPIError(
                "github_api_error",
                "GitHub returned unexpected file metadata. Try again shortly.",
                502,
            )
        if size > MAX_SOURCE_FILE_BYTES:
            raise GitHubAPIError(
                "file_too_large",
                "This file is over the 128 KiB limit. Choose a smaller source file.",
                413,
            )

        encoded_content = payload.get("content")
        if not isinstance(encoded_content, str) or payload.get("encoding") != "base64":
            raise GitHubAPIError(
                "unsupported_file",
                "GitHub did not return a supported text file. Choose another source file.",
                415,
            )
        try:
            content_bytes = base64.b64decode("".join(encoded_content.split()), validate=True)
            content = content_bytes.decode("utf-8", errors="strict")
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            raise GitHubAPIError(
                "unsupported_file",
                "This file is binary or is not valid UTF-8 text. Choose a text source file.",
                415,
            ) from error

        if len(content_bytes) > MAX_SOURCE_FILE_BYTES or any(
            (byte < 32 and byte not in (9, 10, 12, 13)) or byte == 127
            for byte in content_bytes
        ):
            raise GitHubAPIError(
                "unsupported_file",
                "This file is binary or exceeds the supported text format. Choose another file.",
                415,
            )

        return f"{owner}/{repository}", path, ref, content, len(content_bytes)
    except httpx.TimeoutException as error:
        raise GitHubAPIError(
            "github_timeout",
            "GitHub took too long to return this file. Try again shortly.",
            504,
        ) from error
    except httpx.RequestError as error:
        raise GitHubAPIError(
            "github_unavailable",
            "DevPilot could not reach GitHub. Check your connection and try again.",
            502,
        ) from error
    except (ValueError, ValidationError) as error:
        raise GitHubAPIError(
            "github_api_error",
            "GitHub returned an unexpected file response. Try again shortly.",
            502,
        ) from error
