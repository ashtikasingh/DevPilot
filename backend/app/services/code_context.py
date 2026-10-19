import asyncio
import json
import posixpath
import re
from dataclasses import dataclass

from app.services.github import (
    MAX_SOURCE_FILE_BYTES,
    GitHubAPIError,
    fetch_public_file_content,
    fetch_public_repository_tree,
)

MAX_CONTEXT_FILES = 4
MAX_CONTEXT_BYTES = 256 * 1024
CONTEXT_DEADLINE_SECONDS = 30.0
SOURCE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")
STATIC_RELATIVE_IMPORT_PATTERN = re.compile(
    r"(?m)^[ \t]*(?:import(?!\s*\()|export)\b"
    r"(?:(?!^[ \t]*(?:import|export)\b)[^;])*?"
    r"(?:\bfrom\s*)?([\"'])(\.{1,2}/[^\"']+)\1",
    re.DOTALL,
)


@dataclass(frozen=True)
class ContextSource:
    source_id: str
    path: str
    content: str
    size_bytes: int


@dataclass(frozen=True)
class RelatedContext:
    sources: list[ContextSource]
    complete: bool
    message: str | None


def _numbered_source(source: str) -> str:
    return "\n".join(
        f"{line_number} | {line}"
        for line_number, line in enumerate(source.splitlines(), start=1)
    )


def _serialized_context_size(sources: list[ContextSource]) -> int:
    payload = [
        {
            "source_id": source.source_id,
            "path": source.path,
            "numbered_source": _numbered_source(source.content),
        }
        for source in sources
    ]
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _extract_relative_imports(source: str) -> list[str]:
    """Extract only relative static import/export specifiers from JS/TS text."""
    source = _mask_js_comments_and_templates(source)
    imports: list[str] = []
    for match in STATIC_RELATIVE_IMPORT_PATTERN.finditer(source):
        specifier = match.group(2)
        if specifier.startswith(("./", "../")) and specifier not in imports:
            imports.append(specifier)
    return imports


def _mask_js_comments_and_templates(source: str) -> str:
    """Mask comments and template literals while preserving quote-delimited imports."""
    chars = list(source)
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            elif quote == "`":
                chars[index] = "\n" if char == "\n" else " "
            index += 1
            continue

        if char in ("'", '"', "`"):
            quote = char
            if char == "`":
                chars[index] = " "
            index += 1
            continue
        if source.startswith("//", index):
            while index < len(source) and source[index] != "\n":
                chars[index] = " "
                index += 1
            continue
        if source.startswith("/*", index):
            chars[index] = " "
            if index + 1 < len(source):
                chars[index + 1] = " "
            index += 2
            while index < len(source) and not source.startswith("*/", index):
                if source[index] != "\n":
                    chars[index] = " "
                index += 1
            if index < len(source):
                chars[index] = " "
                if index + 1 < len(source):
                    chars[index + 1] = " "
                index += 2
            continue
        index += 1
    return "".join(chars)


def _resolve_import_path(
    importing_path: str,
    specifier: str,
    available_paths: set[str],
) -> str | None:
    if (
        not specifier.startswith(("./", "../"))
        or "\\" in specifier
        or ":" in specifier
        or "\x00" in specifier
    ):
        return None

    base = posixpath.normpath(posixpath.join(posixpath.dirname(importing_path), specifier))
    if base in {".", ".."} or base.startswith("../") or base.startswith("/"):
        return None

    candidates = [base]
    if not posixpath.splitext(base)[1]:
        candidates.extend(f"{base}{extension}" for extension in SOURCE_EXTENSIONS)
        candidates.extend(
            f"{base}/index{extension}" for extension in SOURCE_EXTENSIONS
        )
    else:
        suffix = posixpath.splitext(base)[1]
        if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
            stem = base[: -len(suffix)]
            candidates.extend(
                f"{stem}{extension}" for extension in (".ts", ".tsx", ".js", ".jsx")
            )

    for candidate in candidates:
        if candidate in available_paths:
            return candidate
    return None


def _source_file_paths(tree_entries: list[object]) -> tuple[set[str], dict[str, int | None]]:
    paths: set[str] = set()
    sizes: dict[str, int | None] = {}
    for entry in tree_entries:
        path = getattr(entry, "path", None)
        entry_type = getattr(entry, "type", None)
        size = getattr(entry, "size", None)
        if (
            isinstance(path, str)
            and entry_type == "blob"
            and path.lower().endswith(SOURCE_EXTENSIONS)
        ):
            paths.add(path)
            sizes[path] = size if isinstance(size, int) and size >= 0 else None
    return paths, sizes


async def build_related_context(
    owner: str,
    repository: str,
    path: str,
    ref: str | None,
) -> RelatedContext:
    """Fetch the selected source plus at most three directly imported JS/TS files."""
    try:
        async with asyncio.timeout(CONTEXT_DEADLINE_SECONDS):
            _repository_name, selected_path, resolved_ref, selected_content, selected_size = (
                await fetch_public_file_content(owner, repository, path, ref)
            )
            if selected_size > MAX_SOURCE_FILE_BYTES:
                raise GitHubAPIError(
                    "file_too_large",
                    "This file is over the 128 KiB limit. Choose a smaller source file.",
                    413,
                )
            sources = [
                ContextSource("F1", selected_path, selected_content, selected_size)
            ]
            total_bytes = _serialized_context_size(sources)
            if total_bytes > MAX_CONTEXT_BYTES:
                raise GitHubAPIError(
                    "context_too_large",
                    "The selected file exceeds the supported total source context limit.",
                    413,
                )
            complete = True
            reasons: list[str] = []

            tree_entries, tree_truncated = await fetch_public_repository_tree(
                owner, repository, resolved_ref, repository_public_verified=True
            )
            if tree_truncated:
                complete = False
                reasons.append("GitHub truncated the repository tree")

            available_paths, path_sizes = _source_file_paths(tree_entries)
            candidates: list[str] = []
            for specifier in _extract_relative_imports(selected_content):
                resolved = _resolve_import_path(selected_path, specifier, available_paths)
                if resolved is None:
                    complete = False
                    reasons.append("one or more relative imports could not be resolved")
                elif resolved != selected_path and resolved not in candidates:
                    candidates.append(resolved)

            if not candidates and _extract_relative_imports(selected_content):
                complete = False

            for candidate in candidates[: MAX_CONTEXT_FILES - 1]:
                if len(sources) >= MAX_CONTEXT_FILES:
                    complete = False
                    reasons.append("the related-file limit was reached")
                    break

                tree_size = path_sizes.get(candidate)
                if tree_size is not None and tree_size > MAX_SOURCE_FILE_BYTES:
                    complete = False
                    reasons.append("a related file exceeded the per-file size limit")
                    continue
                if total_bytes >= MAX_CONTEXT_BYTES:
                    complete = False
                    reasons.append("the total source context limit was reached")
                    break

                try:
                    _, related_path, _, content, size_bytes = await fetch_public_file_content(
                        owner,
                        repository,
                        candidate,
                        resolved_ref,
                        repository_public_verified=True,
                    )
                except GitHubAPIError as error:
                    if error.status_code in (404, 413, 415, 422):
                        complete = False
                        reasons.append("a related import was unavailable or unsupported")
                        continue
                    raise

                if size_bytes > MAX_SOURCE_FILE_BYTES:
                    complete = False
                    reasons.append("a related file exceeded the per-file size limit")
                    continue
                candidate_source = ContextSource(
                    f"F{len(sources) + 1}", related_path, content, size_bytes
                )
                if _serialized_context_size([*sources, candidate_source]) > MAX_CONTEXT_BYTES:
                    complete = False
                    reasons.append("the total source context limit was reached")
                    continue

                sources.append(candidate_source)
                total_bytes = _serialized_context_size(sources)

            if len(candidates) > MAX_CONTEXT_FILES - 1:
                complete = False
                reasons.append("additional related imports were omitted by the file limit")

            message = "; ".join(dict.fromkeys(reasons)) or None
            return RelatedContext(sources=sources, complete=complete, message=message)
    except TimeoutError as error:
        raise GitHubAPIError(
            "github_context_timeout",
            "GitHub took too long to gather related source files. Try again shortly.",
            504,
        ) from error
