import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.exc import SQLAlchemyError

from app.api import repositories
from app.schemas.repository import RepositoryQuestionRequest, RepositoryQuestionResponse
from app.services.code_context import ContextSource, RelatedContext
from app.services.gemini import GeminiAPIError
from app.services.github import GitHubAPIError
from app.services.rate_limit import qa_request_limiter
from starlette.requests import Request


def test_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


class RepositoryQuestionRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        qa_request_limiter.clear()

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
                repositories, "relevant_decisions_for_qa", return_value=[]
            ) as memory_lookup,
            patch.object(
                repositories,
                "fetch_public_file_content",
                new=AsyncMock(return_value=("owner/repo", "src/page.ts", "main", "source", 6)),
            ),
            patch.object(repositories, "answer_about_source", new=AsyncMock(return_value="answer")),
            patch.object(repositories, "build_related_context") as context_builder,
        ):
            response = await repositories.ask_about_repository_file(
                request, test_request(), MagicMock()
            )

        self.assertIsInstance(response, RepositoryQuestionResponse)
        self.assertEqual(response.model_dump(), {
            "repository": "owner/repo",
            "path": "src/page.ts",
            "answer": "answer",
        })
        context_builder.assert_not_called()
        memory_lookup.assert_called_once_with(
            unittest.mock.ANY, "owner", "repo", {"src/page.ts"}
        )

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
            patch.object(repositories, "relevant_decisions_for_qa", return_value=[]),
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(repositories, "answer_about_sources", new=AsyncMock(return_value="answer [F2:L1]")),
        ):
            response = await repositories.ask_about_related_files(
                request, test_request(), MagicMock()
            )

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
            patch.object(repositories, "relevant_decisions_for_qa", return_value=[]),
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(
                repositories,
                "answer_about_sources",
                new=AsyncMock(side_effect=GeminiAPIError("gemini_timeout", "safe message", 504)),
            ),
        ):
            response = await repositories.ask_about_related_files(
                request, test_request(), MagicMock()
            )

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
            response = await repositories.ask_about_related_files(request, test_request())

        self.assertEqual(response.status_code, 504)
        self.assertIn(b"safe timeout", response.body)

    async def test_single_file_memory_read_failure_falls_back_to_code_only_response(self):
        request = RepositoryQuestionRequest(
            owner="owner",
            repository="repo",
            path="src/page.ts",
            ref="main",
            question="Explain this file",
        )
        session = MagicMock()
        with (
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(
                repositories,
                "fetch_public_file_content",
                new=AsyncMock(return_value=("Owner/Repo", "src/page.ts", "main", "source", 6)),
            ),
            patch.object(
                repositories,
                "relevant_decisions_for_qa",
                side_effect=SQLAlchemyError("private database details"),
            ),
            patch.object(
                repositories, "answer_about_source", new=AsyncMock(return_value="answer [L1]")
            ) as answer,
        ):
            response = await repositories.ask_about_repository_file(
                request, test_request(), session
            )

        self.assertEqual(response.model_dump(), {
            "repository": "Owner/Repo",
            "path": "src/page.ts",
            "answer": "answer [L1]",
        })
        self.assertEqual(answer.await_args.kwargs["memory_context"], [])
        session.rollback.assert_called_once()

    async def test_related_memory_scope_uses_normalized_identity_and_included_paths(self):
        request = RepositoryQuestionRequest(
            owner="Owner",
            repository="Repo",
            path="src/page.ts",
            ref="main",
            question="Explain this",
        )
        context = RelatedContext(
            sources=[
                ContextSource("F1", "src/page.ts", "selected", 8),
                ContextSource("F2", "src/helper.ts", "helper", 6),
            ],
            complete=True,
            message=None,
        )
        with (
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(repositories, "relevant_decisions_for_qa", return_value=[]) as memory_lookup,
            patch.object(
                repositories, "answer_about_sources", new=AsyncMock(return_value="answer")
            ),
        ):
            response = await repositories.ask_about_related_files(
                request, test_request(), MagicMock()
            )

        self.assertEqual(response.repository, "Owner/Repo")
        memory_lookup.assert_called_once_with(
            unittest.mock.ANY, "owner", "repo", {"src/page.ts", "src/helper.ts"}
        )

    async def test_related_memory_read_failure_falls_back_without_changing_response(self):
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
        session = MagicMock()
        with (
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(
                repositories,
                "relevant_decisions_for_qa",
                side_effect=SQLAlchemyError("private database details"),
            ),
            patch.object(
                repositories, "answer_about_sources", new=AsyncMock(return_value="answer [F1:L1]")
            ) as answer,
        ):
            response = await repositories.ask_about_related_files(
                request, test_request(), session
            )

        self.assertEqual(response.model_dump(), {
            "repository": "owner/repo",
            "path": "src/page.ts",
            "answer": "answer [F1:L1]",
            "sources": [{"source_id": "F1", "path": "src/page.ts", "size_bytes": 6}],
            "context_complete": True,
            "context_message": None,
        })
        self.assertEqual(answer.await_args.kwargs["memory_context"], [])
        session.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
