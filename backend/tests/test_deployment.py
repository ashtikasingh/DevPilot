import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api import repositories
from app.main import DEFAULT_CORS_ORIGINS, create_app, parse_cors_origins
from app.schemas.repository import (
    InspectRepositoryResponse,
    RepositoryMetadata,
)
from app.services.code_context import ContextSource, RelatedContext
from app.services.rate_limit import InMemorySlidingWindowLimiter, qa_request_limiter


def sample_inspection() -> InspectRepositoryResponse:
    return InspectRepositoryResponse(
        repository=RepositoryMetadata(
            name="repo",
            full_name="owner/repo",
            html_url="https://github.com/owner/repo",
            description=None,
            default_branch="main",
            stargazers_count=0,
        ),
        tree=[],
        tree_complete=True,
        tree_truncated=False,
        tree_message=None,
    )


class CorsConfigurationTests(unittest.TestCase):
    def test_cors_allowlist_trims_and_ignores_empty_entries(self):
        self.assertEqual(
            parse_cors_origins(" https://app.example, , https://preview.example/ "),
            ["https://app.example", "https://preview.example"],
        )

    def test_empty_cors_setting_preserves_localhost_defaults(self):
        self.assertEqual(parse_cors_origins(" , "), list(DEFAULT_CORS_ORIGINS))

    def test_wildcard_or_invalid_origins_are_rejected(self):
        for origin in ("*", "https://*.example.com", "https://app.example/path", "https://bad:port"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                parse_cors_origins(origin)

    def test_configured_origin_is_allowed_and_other_origin_is_not(self):
        with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "https://pilot.example, ,https://other.example"}):
            client = TestClient(create_app())
            allowed = client.options(
                "/api/repositories/inspect",
                headers={
                    "Origin": "https://pilot.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            denied = client.options(
                "/api/repositories/inspect",
                headers={
                    "Origin": "https://attacker.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )

        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "https://pilot.example")
        self.assertNotIn("access-control-allow-origin", denied.headers)


class InMemoryRateLimiterTests(unittest.TestCase):
    def test_sliding_window_expires_requests_and_is_bounded(self):
        now = [100.0]
        limiter = InMemorySlidingWindowLimiter(max_clients=2, clock=lambda: now[0])
        self.assertIsNone(limiter.consume("client-a", 1, 10))
        self.assertEqual(limiter.consume("client-a", 1, 10), 10)
        now[0] += 10
        self.assertIsNone(limiter.consume("client-a", 1, 10))
        limiter.consume("client-b", 1, 10)
        limiter.consume("client-c", 1, 10)
        self.assertLessEqual(len(limiter._requests), 2)

    def test_concurrent_requests_cannot_exceed_the_configured_limit(self):
        limiter = InMemorySlidingWindowLimiter()
        barrier = threading.Barrier(20)

        def consume_request(_index: int) -> int | None:
            barrier.wait()
            return limiter.consume("one-client", 5, 60)

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(consume_request, range(20)))

        self.assertEqual(sum(result is None for result in results), 5)
        self.assertTrue(all(result == 60 for result in results if result is not None))

    def test_new_client_churn_uses_a_shared_bounded_overflow_bucket(self):
        limiter = InMemorySlidingWindowLimiter(max_clients=1)
        self.assertIsNone(limiter.consume("client-a", 1, 60))
        self.assertIsNone(limiter.consume("client-b", 1, 60))
        self.assertEqual(limiter.consume("client-c", 1, 60), 60)
        self.assertLessEqual(len(limiter._requests), 1)

    def test_rate_limit_settings_are_bounded_and_fall_back_safely(self):
        with patch.dict(
            os.environ,
            {"GEMINI_QA_RATE_LIMIT": "999999999999999999999", "GEMINI_QA_RATE_WINDOW_SECONDS": "0"},
        ):
            from app.services.rate_limit import qa_rate_limit_settings

            self.assertEqual(qa_rate_limit_settings(), (10, 60))


class DeploymentEndpointTests(unittest.TestCase):
    def setUp(self):
        qa_request_limiter.clear()

    def tearDown(self):
        qa_request_limiter.clear()

    def test_healthz_is_public_and_exposes_only_a_simple_status(self):
        response = TestClient(create_app()).get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_rate_limit_applies_to_both_qa_routes_but_not_inspection_or_health(self):
        context = RelatedContext(
            sources=[ContextSource("F1", "src/page.ts", "safe test source", 16)],
            complete=True,
            message=None,
        )
        with (
            patch.dict(
                os.environ,
                {"GEMINI_QA_RATE_LIMIT": "1", "GEMINI_QA_RATE_WINDOW_SECONDS": "60"},
            ),
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(
                repositories,
                "inspect_public_repository",
                new=AsyncMock(return_value=sample_inspection()),
            ) as inspect,
            patch.object(
                repositories,
                "fetch_public_file_content",
                new=AsyncMock(return_value=("owner/repo", "src/page.ts", "main", "safe test source", 16)),
            ),
            patch.object(
                repositories, "answer_about_source", new=AsyncMock(return_value="single answer")
            ) as answer_single,
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(
                repositories, "answer_about_sources", new=AsyncMock(return_value="related answer")
            ) as answer_related,
        ):
            client = TestClient(create_app(cors_origins=[]))
            inspection_payload = {"repository_url": "https://github.com/owner/repo"}
            for _ in range(2):
                self.assertEqual(
                    client.post("/api/repositories/inspect", json=inspection_payload).status_code,
                    200,
                )
            self.assertEqual(client.get("/healthz").status_code, 200)

            question_payload = {
                "owner": "owner",
                "repository": "repo",
                "path": "src/page.ts",
                "ref": "main",
                "question": "Explain this file",
            }
            single_response = client.post("/api/repositories/ask", json=question_payload)
            related_response = client.post("/api/repositories/ask-related", json=question_payload)

        self.assertEqual(single_response.status_code, 200)
        self.assertEqual(related_response.status_code, 429)
        self.assertEqual(related_response.json(), {
            "error": {
                "code": "qa_rate_limited",
                "message": "Too many Q&A requests. Wait briefly, then try again.",
                "retry_after_seconds": 60,
            }
        })
        self.assertEqual(related_response.headers.get("retry-after"), "60")
        self.assertEqual(inspect.await_count, 2)
        answer_single.assert_awaited_once()
        answer_related.assert_not_awaited()

        qa_request_limiter.clear()
        with (
            patch.dict(
                os.environ,
                {"GEMINI_QA_RATE_LIMIT": "1", "GEMINI_QA_RATE_WINDOW_SECONDS": "60"},
            ),
            patch.object(repositories, "validate_gemini_configuration"),
            patch.object(repositories, "build_related_context", new=AsyncMock(return_value=context)),
            patch.object(repositories, "answer_about_sources", new=AsyncMock(return_value="answer")),
            patch.object(repositories, "fetch_public_file_content", new=AsyncMock()),
            patch.object(repositories, "answer_about_source", new=AsyncMock()) as answer_single,
        ):
            client = TestClient(create_app(cors_origins=[]))
            related_response = client.post("/api/repositories/ask-related", json=question_payload)
            single_response = client.post("/api/repositories/ask", json=question_payload)

        self.assertEqual(related_response.status_code, 200)
        self.assertEqual(single_response.status_code, 429)
        answer_single.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
