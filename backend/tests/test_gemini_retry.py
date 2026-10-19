import os
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
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


def response(status_code, payload, headers=None):
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
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

    async def test_429_numeric_retry_after_reports_53050_seconds_and_source(self):
        client = FakeAsyncClient(
            [response(429, {"error": {"message": "private provider detail"}}, {"Retry-After": "53050"})]
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
            patch.object(gemini.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            with self.assertLogs(gemini.LOGGER, level="WARNING") as captured:
                with self.assertRaises(gemini.GeminiAPIError) as raised:
                    await gemini.answer_about_source("owner/repo", "file.py", "source", "question")

        self.assertEqual(raised.exception.code, "gemini_rate_limited")
        self.assertIn("53050 seconds", raised.exception.message)
        self.assertTrue(any("retry_after_seconds=53050 retry_source=retry_after_header" in line for line in captured.output))
        self.assertNotIn("private provider detail", "\n".join(captured.output))
        self.assertEqual(client.post_count, 1)
        sleep.assert_not_awaited()

    async def test_429_retry_info_reports_53050_seconds_and_source(self):
        client = FakeAsyncClient(
            [
                response(
                    429,
                    {
                        "error": {
                            "status": "RESOURCE_EXHAUSTED",
                            "details": [
                                {
                                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                    "retryDelay": "53050s",
                                }
                            ],
                        }
                    },
                )
            ]
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertLogs(gemini.LOGGER, level="WARNING") as captured:
                with self.assertRaises(gemini.GeminiAPIError) as raised:
                    await gemini.answer_about_source("owner/repo", "file.py", "source", "question")

        self.assertIn("53050 seconds", raised.exception.message)
        self.assertTrue(any("retry_after_seconds=53050 retry_source=retry_info" in line for line in captured.output))
        self.assertEqual(client.post_count, 1)

    def test_retry_after_http_date_uses_deterministic_utc_delta(self):
        now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
        retry_date = format_datetime(now + timedelta(seconds=53050), usegmt=True)
        limited = response(429, {"error": {}}, {"Retry-After": retry_date})

        self.assertEqual(gemini._retry_hint(limited, now), (53050, "retry_after_header"))

    def test_invalid_and_expired_http_dates_are_handled_safely(self):
        now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
        invalid = response(429, {"error": {}}, {"Retry-After": "not an HTTP date"})
        expired_date = format_datetime(now - timedelta(seconds=2), usegmt=True)
        expired = response(429, {"error": {}}, {"Retry-After": expired_date})

        self.assertEqual(gemini._retry_hint(invalid, now), (None, "none"))
        self.assertEqual(gemini._retry_hint(expired, now), (0, "retry_after_header"))

    def test_retry_after_header_keeps_precedence_over_retry_info(self):
        limited = response(
            429,
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "99s",
                        }
                    ]
                }
            },
            {"Retry-After": "53"},
        )

        self.assertEqual(gemini._retry_hint(limited), (53, "retry_after_header"))

    def test_oversized_retry_metadata_is_ignored_without_conversion(self):
        huge_digits = "9" * (gemini.MAX_RETRY_HINT_TEXT_LENGTH + 1)
        oversized_header = response(429, {"error": {}}, {"Retry-After": huge_digits})
        oversized_info = response(
            429,
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": f"{huge_digits}s",
                        }
                    ]
                }
            },
        )

        self.assertEqual(gemini._retry_hint(oversized_header), (None, "none"))
        self.assertEqual(gemini._retry_hint(oversized_info), (None, "none"))

    def test_malformed_retry_metadata_is_ignored_safely(self):
        malformed_duration = response(
            429,
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "1e309s",
                        }
                    ]
                }
            },
            {"Retry-After": "not-a-date"},
        )
        self.assertEqual(gemini._retry_hint(malformed_duration), (None, "none"))

    def test_retry_duration_conversion_overflow_falls_back_safely(self):
        limited = response(
            429,
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "1.5s",
                        }
                    ]
                }
            },
        )
        with patch.object(gemini.math, "ceil", side_effect=OverflowError):
            self.assertEqual(gemini._retry_hint(limited), (None, "none"))

    async def test_429_without_valid_retry_metadata_does_not_guess_wait(self):
        for payload, headers in (
            ({"error": {"status": "RESOURCE_EXHAUSTED"}}, None),
            (
                {
                    "error": {
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": "wait a bit",
                            }
                        ]
                    }
                },
                None,
            ),
            (
                {
                    "error": {
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": "9" * (gemini.MAX_RETRY_HINT_TEXT_LENGTH + 1),
                            }
                        ]
                    }
                },
                {"Retry-After": "9" * (gemini.MAX_RETRY_HINT_TEXT_LENGTH + 1)},
            ),
        ):
            with self.subTest(headers=headers):
                client = FakeAsyncClient([response(429, payload, headers)])
                with (
                    patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                    patch.object(gemini.httpx, "AsyncClient", return_value=client),
                ):
                    with self.assertRaises(gemini.GeminiAPIError) as raised:
                        await gemini.answer_about_source(
                            "owner/repo", "file.py", "source", "question"
                        )

                self.assertIn("did not provide a reliable retry time", raised.exception.message)
                self.assertEqual(client.post_count, 1)


if __name__ == "__main__":
    unittest.main()
