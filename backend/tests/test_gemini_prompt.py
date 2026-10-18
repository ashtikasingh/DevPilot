import os
import unittest
from unittest.mock import patch

import httpx

from app.services import gemini


class CapturingAsyncClient:
    def __init__(self, **kwargs):
        self.request_body = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers, json):
        self.request_body = json
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "## Overview\nAnswer"}]}}]},
            request=httpx.Request("POST", url),
        )


class GeminiPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_numbers_source_and_requests_evidence_based_structure(self):
        client = CapturingAsyncClient()
        source = "function Dashboard() {\n  return 42;\n}\n"
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
        ):
            answer = await gemini.answer_about_source(
                "owner/repo", "src/Dashboard.tsx", source, "Explain this component"
            )

        system_instruction = client.request_body["systemInstruction"]["parts"][0]["text"]
        prompt = client.request_body["contents"][0]["parts"][0]["text"]
        self.assertEqual(answer, "## Overview\nAnswer")
        self.assertIn("nested named functions", system_instruction)
        self.assertIn("group routine callbacks", system_instruction)
        self.assertIn("Do not infer line numbers", system_instruction)
        self.assertIn("Return Markdown text directly", system_instruction)
        self.assertIn("1 | function Dashboard() {", prompt)
        self.assertIn("2 |   return 42;", prompt)
        self.assertIn("3 | }", prompt)


if __name__ == "__main__":
    unittest.main()
