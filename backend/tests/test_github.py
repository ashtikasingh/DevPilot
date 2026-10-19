import base64
import os
import unittest
from unittest.mock import patch

import httpx

from app.services import github


class FakeAsyncClient:
    def __init__(self, responses, **kwargs):
        self.responses = list(responses)
        self.headers = kwargs.get("headers", {})
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def response(status_code, payload=None, headers=None):
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request("GET", "https://api.github.com/"),
    )


def file_response():
    content = base64.b64encode(b"export const value = 1;\n").decode()
    return response(200, {
        "type": "file",
        "size": len(base64.b64decode(content)),
        "encoding": "base64",
        "content": content,
    })


class GitHubRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        github._TREE_CACHE.clear()

    async def test_file_request_uses_optional_bearer_token(self):
        public_metadata = response(200, {"private": False})
        cases = (
            ("test-github-token", "Bearer test-github-token", [public_metadata, file_response()], 2),
            ("", None, [file_response()], 1),
        )
        for configured_token, expected_header, responses, expected_calls in cases:
            with self.subTest(authenticated=bool(configured_token)):
                client = FakeAsyncClient(responses)
                with (
                    patch.dict(os.environ, {"GITHUB_TOKEN": configured_token}),
                    patch.object(
                        github.httpx,
                        "AsyncClient",
                        return_value=client,
                    ) as client_factory,
                ):
                    await github.fetch_public_file_content(
                        "owner", "repo", "src/file.ts", "main"
                    )

                request_headers = client_factory.call_args.kwargs["headers"]
                self.assertEqual(request_headers.get("Authorization"), expected_header)
                self.assertEqual(len(client.calls), expected_calls)

    async def test_token_cannot_be_used_to_read_a_private_repository(self):
        client = FakeAsyncClient([response(200, {"private": True})])
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "test-github-token"}),
            patch.object(github.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(github.GitHubAPIError) as raised:
                await github.fetch_public_file_content(
                    "owner", "repo", "src/file.ts", "main"
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(len(client.calls), 1)

    async def test_authenticated_inspection_rejects_metadata_without_explicit_public_flag(self):
        invalid_values = (("true", True), ("string", "false"), ("integer", 0), ("null", None), ("missing", ...))
        for label, value in invalid_values:
            with self.subTest(private=label):
                payload = {
                    "name": "repo",
                    "full_name": "owner/repo",
                    "html_url": "https://github.com/owner/repo",
                    "default_branch": "main",
                }
                if value is not ...:
                    payload["private"] = value
                client = FakeAsyncClient([response(200, payload)])
                with (
                    patch.dict(os.environ, {"GITHUB_TOKEN": "configured-token"}),
                    patch.object(github.httpx, "AsyncClient", return_value=client),
                ):
                    with self.assertRaises(github.GitHubAPIError) as raised:
                        await github.inspect_public_repository(
                            "https://github.com/owner/repo"
                        )

                self.assertEqual(raised.exception.code, "repository_not_found")
                self.assertEqual(raised.exception.status_code, 404)
                self.assertEqual(
                    raised.exception.message,
                    "Repository was not found or is not public. Check the URL and repository visibility.",
                )
                self.assertNotIn("configured-token", raised.exception.message)
                self.assertEqual(len(client.calls), 1)

    async def test_authenticated_inspection_accepts_only_explicit_private_false(self):
        metadata = response(200, {
            "name": "repo",
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
            "default_branch": "main",
            "private": False,
        })
        tree = response(200, {"tree": [], "truncated": False})
        client = FakeAsyncClient([metadata, tree])
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "configured-token"}),
            patch.object(github.httpx, "AsyncClient", return_value=client),
        ):
            result = await github.inspect_public_repository(
                "https://github.com/owner/repo"
            )

        self.assertEqual(result.repository.full_name, "owner/repo")
        self.assertEqual(len(client.calls), 2)

    async def test_unauthenticated_inspection_keeps_missing_private_behavior(self):
        metadata = response(200, {
            "name": "repo",
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
            "default_branch": "main",
        })
        tree = response(200, {"tree": [], "truncated": False})
        client = FakeAsyncClient([metadata, tree])
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": ""}),
            patch.object(github.httpx, "AsyncClient", return_value=client),
        ):
            result = await github.inspect_public_repository(
                "https://github.com/owner/repo"
            )

        self.assertEqual(result.repository.full_name, "owner/repo")
        self.assertEqual(len(client.calls), 2)

    def test_retry_after_header_sets_actionable_wait(self):
        limited = response(
            403,
            {"message": "API rate limit exceeded"},
            {"X-RateLimit-Remaining": "0", "Retry-After": "37"},
        )

        with self.assertRaises(github.GitHubAPIError) as raised:
            github._raise_for_github_error(limited)

        self.assertEqual(raised.exception.retry_after_seconds, 37)
        self.assertIn("37 seconds", raised.exception.message)

    def test_reset_epoch_sets_actionable_wait_when_retry_after_is_absent(self):
        limited = response(
            403,
            {"message": "API rate limit exceeded"},
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1065"},
        )

        with patch.object(github.time, "time", return_value=1000):
            with self.assertRaises(github.GitHubAPIError) as raised:
                github._raise_for_github_error(limited)

        self.assertEqual(raised.exception.retry_after_seconds, 65)
        self.assertIn("65 seconds", raised.exception.message)

    async def test_rate_limit_stops_after_the_first_request_without_retrying(self):
        limited = response(
            403,
            {"message": "API rate limit exceeded"},
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1065"},
        )
        client = FakeAsyncClient([limited])
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": ""}),
            patch.object(github.httpx, "AsyncClient", return_value=client),
            patch.object(github.time, "time", return_value=1000),
        ):
            with self.assertRaises(github.GitHubAPIError) as raised:
                await github.inspect_public_repository("https://github.com/owner/repo")

        self.assertEqual(raised.exception.code, "github_rate_limited")
        self.assertEqual(len(client.calls), 1)

    async def test_recent_repository_tree_is_reused_without_another_api_request(self):
        tree = response(200, {
            "tree": [{"path": "src/file.ts", "type": "blob", "sha": "test-sha", "size": 8}],
            "truncated": False,
        })
        client = FakeAsyncClient([tree])
        with patch.object(github.httpx, "AsyncClient", return_value=client):
            first = await github.fetch_public_repository_tree("owner", "repo", "main")
            second = await github.fetch_public_repository_tree("owner", "repo", "main")

        self.assertEqual(first, second)
        self.assertEqual(len(client.calls), 1)

    def test_retry_after_without_rate_limit_evidence_is_not_misclassified(self):
        unavailable = response(503, {"message": "Service unavailable"}, {"Retry-After": "30"})

        with self.assertRaises(github.GitHubAPIError) as raised:
            github._raise_for_github_error(unavailable)

        self.assertEqual(raised.exception.code, "github_api_error")


if __name__ == "__main__":
    unittest.main()
