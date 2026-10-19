import unittest
from unittest.mock import AsyncMock, patch

from app.api import repositories
from app.schemas.repository import RepositoryQuestionRequest, RepositoryQuestionResponse
from app.services.code_context import ContextSource, RelatedContext
from app.services.gemini import GeminiAPIError
from app.services.github import GitHubAPIError


class RepositoryQuestionRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_single_file_endpoint_keeps_its_contract(self):
        request = RepositoryQuestionRequest(
            owner="owner",
            repository="repo",
            path="src/page.ts",
            ref="main",
            question="Explain this file",
        )
        with (
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(
                repositories,
                "fetch_public_file_content",
                new=AsyncMock(return_value=("owner/repo", "src/page.ts", "main", "source", 6)),
            ),
            patch.object(repositories, "answer_about_source", new=AsyncMock(return_value="answer")),
            patch.object(repositories, "build_related_context") as context_builder,
        ):
            response = await repositories.ask_about_repository_file(request)

        self.assertIsInstance(response, RepositoryQuestionResponse)
        self.assertEqual(response.model_dump(), {
            "repository": "owner/repo",
            "path": "src/page.ts",
            "answer": "answer",
        })
        context_builder.assert_not_called()

    async def test_related_endpoint_returns_sources_and_partial_coverage(self):
        request = RepositoryQuestionRequest(
            owner="owner",
            repository="repo",
            path="src/page.ts",
            ref="main",
            question="How does this call the helper?",
        )
        context = RelatedContext(
            sources=[
                ContextSource("F1", "src/page.ts", "page source", 11),
                ContextSource("F2", "src/helper.ts", "helper source", 13),
            ],
            complete=False,
            message="GitHub truncated the repository tree",
        )
        with (
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(repositories, "answer_about_sources", new=AsyncMock(return_value="answer [F2:L1]")),
        ):
            response = await repositories.ask_about_related_files(request)

        self.assertEqual(response.model_dump(), {
            "repository": "owner/repo",
            "path": "src/page.ts",
            "answer": "answer [F2:L1]",
            "sources": [
                {"source_id": "F1", "path": "src/page.ts", "size_bytes": 11},
                {"source_id": "F2", "path": "src/helper.ts", "size_bytes": 13},
            ],
            "context_complete": False,
            "context_message": "GitHub truncated the repository tree",
        })

    async def test_related_provider_failure_keeps_safe_error_response(self):
        request = RepositoryQuestionRequest(
            owner="owner",
            repository="repo",
            path="src/page.ts",
            ref="main",
            question="Explain this",
        )
        context = RelatedContext(
            sources=[ContextSource("F1", "src/page.ts", "source", 6)],
            complete=True,
            message=None,
        )
        with (
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(
                repositories,
                "answer_about_sources",
                new=AsyncMock(side_effect=GeminiAPIError("gemini_timeout", "safe message", 504)),
            ),
        ):
            response = await repositories.ask_about_related_files(request)

        self.assertEqual(response.status_code, 504)
        self.assertIn(b"safe message", response.body)
        self.assertNotIn(b"source", response.body)

    async def test_related_github_failure_uses_existing_error_mapping(self):
        request = RepositoryQuestionRequest(
            owner="owner",
            repository="repo",
            path="src/page.ts",
            ref="main",
            question="Explain this",
        )
        with (
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(
                repositories,
                "build_related_context",
                new=AsyncMock(side_effect=GitHubAPIError("github_timeout", "safe timeout", 504)),
            ),
        ):
            response = await repositories.ask_about_related_files(request)

        self.assertEqual(response.status_code, 504)
        self.assertIn(b"safe timeout", response.body)


if __name__ == "__main__":
    unittest.main()
