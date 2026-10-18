import os
import unittest
from unittest.mock import patch

import httpx

from app.services import gemini


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        return self.response


def provider_response(payload):
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/"),
    )


def candidate_response(text, finish_reason="STOP"):
    return {
        "candidates": [{
            "finishReason": finish_reason,
            "content": {"parts": [{"text": text}]},
        }]
    }


class GeminiResponseTests(unittest.IsolatedAsyncioTestCase):
    async def ask_with_response(self, provider_result, source="first line\nsecond line\nthird line"):
        if isinstance(provider_result, httpx.Response):
            response = provider_result
        else:
            response = provider_response(provider_result)
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=FakeAsyncClient(response)),
        ):
            return await gemini.answer_about_source(
                "owner/repo", "file.tsx", source, "Explain this code"
            )

    async def test_valid_single_and_range_citations_are_preserved(self):
        answer = await self.ask_with_response(
            candidate_response("Overview [L1]. Details [L2-L3].")
        )
        self.assertEqual(answer, "Overview [L1]. Details [L2-L3].")

    async def test_malformed_reversed_and_out_of_range_citations_are_sanitized(self):
        answer = await self.ask_with_response(
            candidate_response("Bad [Lx] and [L2-Lx], reversed [L3-L2], missing [L4].")
        )
        self.assertEqual(
            answer,
            "Bad [line reference could not be verified] and "
            "[line reference could not be verified], "
            "reversed [line reference could not be verified], "
            "missing [line reference could not be verified].",
        )

    async def test_citations_in_code_and_unrelated_numeric_text_are_unchanged(self):
        answer = await self.ask_with_response(
            candidate_response(
                "Version 2.17 uses [L2]. Inline `[L999]` stays code.\n"
                "```tsx\nconst marker = '[L999]';\n```\n"
                "Link [L999](https://example.test) stays a link label."
            )
        )
        self.assertIn("Version 2.17 uses [L2].", answer)
        self.assertIn("`[L999]`", answer)
        self.assertIn("const marker = '[L999]';", answer)
        self.assertIn("[L999](https://example.test)", answer)

    async def test_normal_completion_returns_answer(self):
        answer = await self.ask_with_response(candidate_response("Complete answer."))
        self.assertEqual(answer, "Complete answer.")

    async def test_max_tokens_is_reported_as_safe_incomplete_response(self):
        with self.assertRaises(gemini.GeminiAPIError) as raised:
            await self.ask_with_response(candidate_response("Partial answer", "MAX_TOKENS"))

        self.assertEqual(raised.exception.code, "gemini_incomplete_response")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            raised.exception.message,
            "Gemini's answer was cut short. Try a more focused question.",
        )

    async def test_empty_content_uses_existing_safe_error(self):
        with self.assertRaises(gemini.GeminiAPIError) as raised:
            await self.ask_with_response({"candidates": [{"content": {"parts": []}}]})

        self.assertEqual(raised.exception.code, "gemini_empty_response")
        self.assertEqual(raised.exception.status_code, 502)

    async def test_malformed_provider_shapes_use_safe_error(self):
        for payload in ([], {"candidates": {}}, {"candidates": ["not-an-object"]}):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(gemini.GeminiAPIError) as raised:
                    await self.ask_with_response(payload)
                self.assertEqual(raised.exception.code, "gemini_api_error")
                self.assertEqual(raised.exception.status_code, 502)

    async def test_malformed_provider_json_uses_safe_error(self):
        response = httpx.Response(
            200,
            content=b"not-json",
            headers={"Content-Type": "application/json"},
            request=httpx.Request("POST", "https://generativelanguage.googleapis.com/"),
        )
        with self.assertRaises(gemini.GeminiAPIError) as raised:
            await self.ask_with_response(response)

        self.assertEqual(raised.exception.code, "gemini_api_error")
        self.assertNotIn("not-json", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
