import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.services import gemini


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.post_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        self.post_count += 1
        return next(self.responses)


def response(status_code, payload):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/"),
    )


class GeminiRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_503_retries_once_then_returns_answer(self):
        client = FakeAsyncClient(
            [
                response(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}),
                response(
                    200,
                    {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]},
                ),
            ]
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
            patch.object(gemini.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            answer = await gemini.answer_about_source("owner/repo", "file.py", "source", "question")

        self.assertEqual(answer, "answer")
        self.assertEqual(client.post_count, 2)
        sleep.assert_awaited_once_with(gemini.GEMINI_RETRY_BASE_DELAY_SECONDS)

    async def test_persistent_503_exhausts_single_retry(self):
        client = FakeAsyncClient(
            [
                response(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}),
                response(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}),
            ]
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
            patch.object(gemini.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            with self.assertRaises(gemini.GeminiAPIError) as raised:
                await gemini.answer_about_source("owner/repo", "file.py", "source", "question")

        self.assertEqual(raised.exception.code, "gemini_api_error")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(client.post_count, 2)
        sleep.assert_awaited_once_with(gemini.GEMINI_RETRY_BASE_DELAY_SECONDS)

    async def test_client_and_rate_limit_errors_are_not_retried(self):
        for status_code in (400, 401, 403, 429):
            with self.subTest(status_code=status_code):
                client = FakeAsyncClient([response(status_code, {"error": {}})])
                with (
                    patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                    patch.object(gemini.httpx, "AsyncClient", return_value=client),
                    patch.object(gemini.asyncio, "sleep", new_callable=AsyncMock) as sleep,
                ):
                    with self.assertRaises(gemini.GeminiAPIError):
                        await gemini.answer_about_source(
                            "owner/repo", "file.py", "source", "question"
                        )

                self.assertEqual(client.post_count, 1)
                sleep.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
