import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.services import gemini


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.request_bodies = []
        self.post_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers, json):
        self.post_count += 1
        self.request_bodies.append(json)
        return next(self.responses)


def provider_response(status, payload):
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/"),
    )


def successful_response(text, finish_reason="STOP"):
    return provider_response(
        200,
        {"candidates": [{"finishReason": finish_reason, "content": {"parts": [{"text": text}]}}]},
    )


class GeminiSourceContextTests(unittest.IsolatedAsyncioTestCase):
    async def ask(self, text, source_list=None, finish_reason="STOP"):
        client = FakeAsyncClient([successful_response(text, finish_reason)])
        source_list = source_list or [
            ("F1", "src/page.ts", "first line\nsecond line"),
            ("F2", "src/helper.ts", "helper one\nhelper two"),
        ]
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
        ):
            answer = await gemini.answer_about_sources(
                "owner/repo", source_list, "Explain how these files work"
            )
        return answer, client

    async def test_prompt_labels_each_file_and_numbers_lines_independently(self):
        answer, client = await self.ask("F1 describes the entry point [F1:L1].")
        request = client.request_bodies[0]
        system_instruction = request["systemInstruction"]["parts"][0]["text"]
        prompt = request["contents"][0]["parts"][0]["text"]

        self.assertEqual(answer, "F1 describes the entry point [F1:L1].")
        self.assertIn("[F2:L12-L18]", system_instruction)
        self.assertIn(
            "===== BEGIN SOURCE F1 =====\n"
            "Repository path: src/page.ts\n"
            "Numbered source lines:\n"
            "1 | first line\n"
            "2 | second line\n"
            "===== END SOURCE F1 =====",
            prompt,
        )
        self.assertIn(
            "===== BEGIN SOURCE F2 =====\n"
            "Repository path: src/helper.ts\n"
            "Numbered source lines:\n"
            "1 | helper one\n"
            "2 | helper two\n"
            "===== END SOURCE F2 =====",
            prompt,
        )
        self.assertNotIn(r"1 | first line\n2 | second line", prompt)

    async def test_related_mode_uses_2048_tokens_and_requests_concise_file_attribution(self):
        _answer, client = await self.ask("How does the page load its data?")
        request = client.request_bodies[0]
        system_instruction = request["systemInstruction"]["parts"][0]["text"]

        self.assertEqual(request["generationConfig"]["maxOutputTokens"], 3072)
        self.assertIn("Answer the specific question directly in concise Markdown", system_instruction)
        self.assertIn("identify the responsible included file by its source ID and path", system_instruction)
        self.assertIn("Avoid broad repository summaries and repeated explanations", system_instruction)
        self.assertIn("[F1:L12] or [F2:L12-L18]", system_instruction)

    async def test_citation_instructions_list_only_actual_source_ids_and_paths(self):
        _answer, client = await self.ask(
            "Explain the supplied files.",
            source_list=[
                ("F1", "src/page.ts", "entry point"),
                ("F2", "src/helper.ts", "helper"),
            ],
        )
        system_instruction = client.request_bodies[0]["systemInstruction"]["parts"][0]["text"]

        self.assertIn(
            'Only these included source IDs and repository-relative paths may be cited: '
            'F1 ("src/page.ts"), '
            'F2 ("src/helper.ts").',
            system_instruction,
        )
        self.assertNotIn('F3 ("', system_instruction)
        self.assertNotIn('F4 ("', system_instruction)
        self.assertIn("Each file has independent 1-based line numbers", system_instruction)
        self.assertIn("Do not invent source IDs or line references", system_instruction)

    async def test_provider_state_and_value_declarations_get_distinct_citation_guidance(self):
        _answer, client = await self.ask(
            "Explain where provider state is initialized and what it exposes.",
            source_list=[
                ("F1", "client/src/pages/Dashboard.tsx", "consumer"),
                ("F3", "client/src/context/AppContext.tsx", "provider declarations"),
                ("F4", "client/src/types/index.ts", "types"),
            ],
        )
        system_instruction = client.request_bodies[0]["systemInstruction"]["parts"][0]["text"]

        self.assertIn(
            'Only these included source IDs and repository-relative paths may be cited: '
            'F1 ("client/src/pages/Dashboard.tsx"), '
            'F3 ("client/src/context/AppContext.tsx"), '
            'F4 ("client/src/types/index.ts").',
            system_instruction,
        )
        self.assertIn(
            "describing where provider state is initialized, cite the relevant useState declaration "
            "with its actual included source ID and exact 1-based line number or range",
            system_instruction,
        )
        self.assertIn(
            "describing what the provider exposes to consumers, cite the separate provider value "
            "declaration using its actual included source ID and exact 1-based line number or range",
            system_instruction,
        )
        self.assertIn("These are distinct claims and may require distinct citations", system_instruction)
        self.assertIn(
            "explicitly say it cannot be verified from the available context without inventing a citation",
            system_instruction,
        )

    async def test_incomplete_context_instructs_a_limitation_without_fabricated_citation(self):
        answer, client = await self.ask(
            "The supplied files do not establish where the caller is implemented.",
            source_list=[("F1", "src/page.ts", "entry point without its imported helper")],
        )
        system_instruction = client.request_bodies[0]["systemInstruction"]["parts"][0]["text"]

        self.assertIn(
            "If a claim cannot be supported by the supplied context, state that limitation "
            "without fabricating a citation",
            system_instruction,
        )
        self.assertIn("Do not assume unlisted files are available", system_instruction)
        self.assertIn(
            'Only these included source IDs and repository-relative paths may be cited: '
            'F1 ("src/page.ts").',
            system_instruction,
        )
        self.assertNotIn('F2 ("', system_instruction)
        self.assertEqual(answer, "The supplied files do not establish where the caller is implemented.")

    async def test_missing_source_context_returns_safe_error_without_provider_request(self):
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(
                gemini.httpx,
                "AsyncClient",
                side_effect=AssertionError("No provider request should be made"),
            ),
        ):
            with self.assertRaises(gemini.GeminiAPIError) as raised:
                await gemini.answer_about_sources("owner/repo", [], "question")

        self.assertEqual(raised.exception.code, "gemini_empty_context")

    async def test_valid_file_line_citations_are_preserved(self):
        answer, _ = await self.ask("Uses the helper [F2:L1-L2] and entry [F1:L2].")
        self.assertEqual(answer, "Uses the helper [F2:L1-L2] and entry [F1:L2].")

    async def test_property_access_citations_use_the_exact_supplied_lines(self):
        source_list = [
            (
                "F1",
                "src/pages/Dashboard.tsx",
                "dailyCalorieBurn = activity.calories\n"
                "weight = profile.weight\n"
                "height = profile.height",
            ),
        ]
        answer, client = await self.ask(
            "dailyCalorieBurn comes from activity.calories [F1:L1]; "
            "weight comes from profile.weight [F1:L2]; "
            "height comes from profile.height [F1:L3].",
            source_list=source_list,
        )

        self.assertEqual(
            answer,
            "dailyCalorieBurn comes from activity.calories [F1:L1]; "
            "weight comes from profile.weight [F1:L2]; "
            "height comes from profile.height [F1:L3].",
        )
        request = client.request_bodies[0]
        system_instruction = request["systemInstruction"]["parts"][0]["text"]
        prompt = request["contents"][0]["parts"][0]["text"]
        self.assertIn("cite the exact numbered line containing that access", system_instruction)
        self.assertIn(
            "1 | dailyCalorieBurn = activity.calories\n"
            "2 | weight = profile.weight\n"
            "3 | height = profile.height",
            prompt,
        )

    async def test_out_of_range_property_access_citations_are_sanitized(self):
        with self.assertLogs(gemini.LOGGER, level="INFO") as captured:
            answer, _ = await self.ask(
                "dailyCalorieBurn [F1:L4], weight [F1:L5], height [F1:L6].",
                source_list=[
                    (
                        "F1",
                        "src/pages/Dashboard.tsx",
                        "dailyCalorieBurn = activity.calories\n"
                        "weight = profile.weight\n"
                        "height = profile.height",
                    ),
                ],
            )

        replacement = "[source reference could not be verified]"
        self.assertEqual(
            answer,
            f"dailyCalorieBurn {replacement}, weight {replacement}, height {replacement}.",
        )
        self.assertIn("invalid_line_range=3", "\n".join(captured.output))

    async def test_citation_failures_are_sanitized_and_logged_by_safe_category(self):
        with self.assertLogs(gemini.LOGGER, level="INFO") as captured:
            answer, _ = await self.ask(
                "Bad [F5:L1], malformed [F2:Lx], reversed [F2:L2-L1], "
                "out of range [F1:L3]."
            )
        self.assertEqual(
            answer,
            "Bad [source reference could not be verified], "
            "malformed [source reference could not be verified], "
            "reversed [source reference could not be verified], "
            "out of range [source reference could not be verified].",
        )
        diagnostics = "\n".join(captured.output)
        self.assertIn("malformed_syntax=1", diagnostics)
        self.assertIn("unknown_source_id=1", diagnostics)
        self.assertIn("invalid_line_range=2", diagnostics)

    async def test_literal_unverified_reference_phrase_from_provider_is_preserved(self):
        provider_text = "[source reference could not be verified]"

        with self.assertNoLogs(gemini.LOGGER, level="INFO"):
            answer, _ = await self.ask(provider_text)

        self.assertEqual(answer, provider_text)

    async def test_line_87_is_valid_for_the_third_source_and_keeps_its_mapping(self):
        source_list = [
            ("F1", "src/pages/Dashboard.tsx", "selected file"),
            ("F2", "src/assets.ts", "assets file"),
            ("F3", "src/context/AppContext.tsx", "\n".join(f"line {line}" for line in range(1, 88))),
            ("F4", "src/types/index.ts", "type definitions"),
        ]
        answer, client = await self.ask(
            "The context value is defined here [F3:L87].", source_list=source_list
        )

        self.assertEqual(answer, "The context value is defined here [F3:L87].")
        prompt = client.request_bodies[0]["contents"][0]["parts"][0]["text"]
        self.assertIn("Repository path: src/context/AppContext.tsx", prompt)
        self.assertIn("87 | line 87\n===== END SOURCE F3 =====", prompt)

    async def test_code_and_unrelated_text_are_preserved_during_citation_validation(self):
        answer, _ = await self.ask(
            "Version 2.17; inline `[F2:L999]`.\n"
            "```ts\nconst x = '[F2:L999]';\n```\n"
            "Unknown [F3:L1]."
        )
        self.assertIn("Version 2.17", answer)
        self.assertIn("`[F2:L999]`", answer)
        self.assertIn("const x = '[F2:L999]';", answer)
        self.assertIn("[source reference could not be verified]", answer)

    async def test_max_tokens_and_empty_content_use_safe_provider_errors(self):
        for payload, code in (
            ({"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "partial"}]}}]}, "gemini_incomplete_response"),
            ({"candidates": [{"content": {"parts": []}}]}, "gemini_empty_response"),
        ):
            client = FakeAsyncClient([provider_response(200, payload)])
            with (
                patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                patch.object(gemini.httpx, "AsyncClient", return_value=client),
            ):
                with self.assertRaises(gemini.GeminiAPIError) as raised:
                    await gemini.answer_about_sources(
                        "owner/repo", [("F1", "src/page.ts", "source")], "question"
                    )
            self.assertEqual(raised.exception.code, code)

    async def test_persistent_provider_503_uses_existing_bounded_retry_and_safe_error(self):
        failure = provider_response(503, {"error": {"status": "UNAVAILABLE"}})
        client = FakeAsyncClient([failure, failure])
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch.object(gemini.httpx, "AsyncClient", return_value=client),
            patch.object(gemini.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            with self.assertRaises(gemini.GeminiAPIError) as raised:
                await gemini.answer_about_sources(
                    "owner/repo", [("F1", "src/page.ts", "secret source")], "private question"
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(client.post_count, 2)
        sleep.assert_awaited_once_with(gemini.GEMINI_RETRY_BASE_DELAY_SECONDS)
        self.assertNotIn("secret source", raised.exception.message)
        self.assertNotIn("private question", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
