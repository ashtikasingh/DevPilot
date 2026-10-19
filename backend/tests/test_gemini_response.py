import os
import unittest
from unittest.mock import patch

import httpx

from app.services import gemini


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.request_bodies = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        self.request_bodies.append(kwargs.get("json"))
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
            "Bad [citation syntax or line range could not be verified] and "
            "[citation syntax or line range could not be verified], "
            "reversed [citation syntax or line range could not be verified], "
            "missing [citation syntax or line range could not be verified].",
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

    async def test_single_file_mode_uses_2048_output_token_limit(self):
        client = FakeAsyncClient(provider_response(candidate_response("Complete answer.")))
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
        ):
            await gemini.answer_about_source(
                "owner/repo", "file.tsx", "const answer = 42;", "Explain this file"
            )

        self.assertEqual(
            client.request_bodies[0]["generationConfig"]["maxOutputTokens"], 2048
        )

    async def test_max_tokens_is_reported_as_safe_incomplete_response(self):
        with self.assertRaises(gemini.GeminiAPIError) as raised:
            await self.ask_with_response(candidate_response("Partial answer", "MAX_TOKENS"))

        self.assertEqual(raised.exception.code, "gemini_incomplete_response")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            raised.exception.message,
            "Gemini's answer was cut short. Try a more focused question.",
        )

    async def test_max_tokens_diagnostics_include_only_safe_counts(self):
        payload = candidate_response("private source and question", "MAX_TOKENS")
        payload["usageMetadata"] = {
            "promptTokenCount": 120,
            "candidatesTokenCount": 2048,
            "totalTokenCount": 2168,
        }
        with self.assertLogs(gemini.LOGGER, level="WARNING") as captured:
            with self.assertRaises(gemini.GeminiAPIError):
                await self.ask_with_response(payload)

        logs = "\n".join(captured.output)
        self.assertIn("finish_reason=max_tokens", logs)
        self.assertIn("output_token_limit=2048", logs)
        self.assertIn("prompt_tokens=120", logs)
        self.assertIn("candidate_tokens=2048", logs)
        self.assertIn("total_tokens=2168", logs)
        self.assertNotIn("private source", logs)
        self.assertNotIn("question", logs)

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
