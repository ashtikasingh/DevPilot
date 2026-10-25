import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app import main
from app.api import decisions as decisions_api
from app.database import create_database
from app.schemas.decision import DecisionCreate, DecisionUpdate
from app.services import github
from app.services.rate_limit import decision_write_limiter, qa_request_limiter


class FakeAsyncClient:
    def __init__(self, response, **kwargs):
        self.response = response
        self.headers = kwargs.get("headers", {})
        self.timeout = kwargs.get("timeout")
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def github_response(status_code=200, payload=None, headers=None):
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request("GET", "https://api.github.com/repos/owner/repo"),
    )


class PublicRepositoryVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_verifier_requires_explicit_public_metadata_and_returns_canonical_name(self):
        client = FakeAsyncClient(
            github_response(
                payload={
                    "private": False,
                    "full_name": "CanonicalOwner/CanonicalRepo",
                }
            )
        )
        with patch.object(github.httpx, "AsyncClient", return_value=client) as factory:
            result = await github.verify_public_repository("owner", "repo")

        self.assertEqual(result, ("CanonicalOwner", "CanonicalRepo"))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(factory.call_args.kwargs["timeout"], github.REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(client.calls[0][0], "/repos/owner/repo")
        factory.assert_called_once()

    async def test_verifier_rejects_private_missing_and_non_boolean_visibility(self):
        for value in (True, "false", 0, None, ...):
            with self.subTest(private=value):
                payload = {"full_name": "owner/repo"}
                if value is not ...:
                    payload["private"] = value
                client = FakeAsyncClient(github_response(payload=payload))
                with patch.object(github.httpx, "AsyncClient", return_value=client):
                    with self.assertRaises(github.GitHubAPIError) as raised:
                        await github.verify_public_repository("owner", "repo")
                self.assertEqual(raised.exception.code, "repository_not_found")
                self.assertEqual(raised.exception.status_code, 404)

    async def test_verifier_maps_timeout_and_rate_limit_without_retrying(self):
        timeout_client = FakeAsyncClient(httpx.ReadTimeout("private transport detail"))
        with patch.object(github.httpx, "AsyncClient", return_value=timeout_client):
            with self.assertRaises(github.GitHubAPIError) as timeout_error:
                await github.verify_public_repository("owner", "repo")
        self.assertEqual(timeout_error.exception.status_code, 504)
        self.assertNotIn("private transport detail", timeout_error.exception.message)
        self.assertEqual(len(timeout_client.calls), 1)

        limited_client = FakeAsyncClient(
            github_response(429, {"message": "private upstream detail"}, {"Retry-After": "37"})
        )
        with patch.object(github.httpx, "AsyncClient", return_value=limited_client):
            with self.assertRaises(github.GitHubAPIError) as limited_error:
                await github.verify_public_repository("owner", "repo")
        self.assertEqual(limited_error.exception.status_code, 429)
        self.assertEqual(limited_error.exception.retry_after_seconds, 37)
        self.assertNotIn("private upstream detail", limited_error.exception.message)
        self.assertEqual(len(limited_client.calls), 1)


class DecisionSchemaTests(unittest.TestCase):
    def test_text_is_trimmed_and_source_path_is_validated(self):
        decision = DecisionCreate(
            title="  Choice  ",
            content="  Use a bounded cache.  ",
            source_path="src/cache.ts",
        )
        self.assertEqual(decision.title, "Choice")
        self.assertEqual(decision.content, "Use a bounded cache.")
        for path in ("/absolute.ts", "../secret.ts", "src/../secret.ts", "a\\b", "a//b", " "):
            with self.subTest(path=path), self.assertRaises(ValueError):
                DecisionCreate(title="A", content="B", source_path=path)

    def test_length_limits_and_empty_patch_are_rejected(self):
        with self.assertRaises(ValueError):
            DecisionCreate(title="x" * 121, content="valid")
        with self.assertRaises(ValueError):
            DecisionCreate(title="valid", content="x" * 4001)
        with self.assertRaises(ValueError):
            DecisionUpdate()
        with self.assertRaises(ValueError):
            DecisionUpdate(title=None)

    def test_database_url_can_be_configured_without_echoing_invalid_details(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "configured.db"
            with patch.dict(os.environ, {"DEVPILOT_DATABASE_URL": f"sqlite:///{path.as_posix()}"}):
                database = create_database()
            try:
                self.assertEqual(database.engine.url.database, path.as_posix())
            finally:
                database.engine.dispose()

        configured_url = "postgresql://host/database"
        with self.assertRaisesRegex(RuntimeError, "supports SQLite only") as raised:
            create_database(configured_url)
        self.assertNotIn(configured_url, str(raised.exception))


class DecisionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "test.db"
        self.app = main.create_app(
            cors_origins=[],
            database_url=f"sqlite:///{self.database_path.as_posix()}",
        )
        decision_write_limiter.clear()
        qa_request_limiter.clear()

    def tearDown(self):
        decision_write_limiter.clear()
        qa_request_limiter.clear()
        self.temporary_directory.cleanup()

    @staticmethod
    async def _canonical(owner: str, repository: str) -> tuple[str, str]:
        return owner.capitalize(), repository.capitalize()

    def test_create_list_update_and_delete_are_persisted_in_repository_scope(self):
        with (
            patch.object(decisions_api, "verify_public_repository", new=AsyncMock(side_effect=self._canonical)),
            TestClient(self.app) as client,
        ):
            created = client.post(
                "/api/repositories/owner/repo/decisions",
                json={"title": "Use stable IDs", "content": "Keep decision keys scoped.", "source_path": "src/store.ts"},
            )
            self.assertEqual(created.status_code, 201)
            created_data = created.json()
            UUID(created_data["id"])
            self.assertEqual(created_data["repository"], "Owner/Repo")
            self.assertEqual(created_data["source_path"], "src/store.ts")
            created_at = datetime.fromisoformat(created_data["created_at"].replace("Z", "+00:00"))
            self.assertEqual(created_at.utcoffset(), timezone.utc.utcoffset(created_at))

            listed = client.get("/api/repositories/OWNER/REPO/decisions")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([entry["id"] for entry in listed.json()["decisions"]], [created_data["id"]])

            updated = client.patch(
                f"/api/repositories/owner/repo/decisions/{created_data['id']}",
                json={"title": "Updated decision", "source_path": None},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["title"], "Updated decision")
            self.assertIsNone(updated.json()["source_path"])

            removed = client.delete(
                f"/api/repositories/owner/repo/decisions/{created_data['id']}"
            )
            self.assertEqual(removed.status_code, 204)
            self.assertEqual(client.get("/api/repositories/owner/repo/decisions").json()["decisions"], [])

    def test_update_and_delete_cannot_cross_repository_scope(self):
        with (
            patch.object(decisions_api, "verify_public_repository", new=AsyncMock(side_effect=self._canonical)),
            TestClient(self.app) as client,
        ):
            created = client.post(
                "/api/repositories/owner/repo/decisions",
                json={"title": "Decision", "content": "Scoped content"},
            )
            decision_id = created.json()["id"]
            cross_update = client.patch(
                f"/api/repositories/other/repo/decisions/{decision_id}",
                json={"title": "Changed"},
            )
            cross_delete = client.delete(
                f"/api/repositories/other/repo/decisions/{decision_id}"
            )
            other_list = client.get("/api/repositories/other/repo/decisions")
            original = client.get("/api/repositories/owner/repo/decisions")

        self.assertEqual(cross_update.status_code, 404)
        self.assertEqual(cross_delete.status_code, 404)
        self.assertEqual(other_list.json()["decisions"], [])
        self.assertEqual(original.json()["decisions"][0]["content"], "Scoped content")

    def test_invalid_payload_has_safe_validation_error_and_skips_github(self):
        with (
            patch.object(decisions_api, "verify_public_repository", new=AsyncMock()) as verify,
            TestClient(self.app) as client,
        ):
            response = client.post(
                "/api/repositories/owner/repo/decisions",
                json={"title": "", "content": "private content", "source_path": "../outside"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private content", response.text)
        verify.assert_not_awaited()

    def test_database_errors_return_generic_response_without_error_details(self):
        with (
            patch.object(decisions_api, "verify_public_repository", new=AsyncMock(side_effect=self._canonical)),
            patch.object(
                decisions_api,
                "create_decision",
                side_effect=SQLAlchemyError("sensitive SQL and content detail"),
            ),
            self.assertLogs(decisions_api.logger, level="WARNING") as captured,
            TestClient(self.app) as client,
        ):
            response = client.post(
                "/api/repositories/owner/repo/decisions",
                json={"title": "Decision", "content": "content"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive SQL", response.text)
        self.assertNotIn("sensitive SQL", "".join(captured.output))
        self.assertIn("exception_type=SQLAlchemyError", "".join(captured.output))

    def test_write_rate_limit_is_separate_and_returns_retry_after(self):
        with (
            patch.object(decisions_api, "DECISION_WRITE_RATE_LIMIT", 1),
            patch.object(decisions_api, "verify_public_repository", new=AsyncMock(side_effect=self._canonical)) as verify,
            TestClient(self.app) as client,
        ):
            payload = {"title": "Decision", "content": "Content"}
            allowed = client.post("/api/repositories/owner/repo/decisions", json=payload)
            rejected = client.post("/api/repositories/owner/repo/decisions", json=payload)

        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(rejected.headers.get("retry-after"), "60")
        self.assertEqual(verify.await_count, 1)
        self.assertIsNot(decision_write_limiter, qa_request_limiter)

    def test_cors_allows_memory_write_methods(self):
        app = main.create_app(cors_origins=["https://devpilot.example"], database_url="sqlite:///:memory:")
        client = TestClient(app)
        for method in ("PATCH", "DELETE"):
            response = client.options(
                "/api/repositories/owner/repo/decisions/example",
                headers={
                    "Origin": "https://devpilot.example",
                    "Access-Control-Request-Method": method,
                },
            )
            self.assertEqual(response.headers.get("access-control-allow-origin"), "https://devpilot.example")
            self.assertIn(method, response.headers.get("access-control-allow-methods", ""))
        app.state.database.engine.dispose()


if __name__ == "__main__":
    unittest.main()
