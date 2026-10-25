import json
import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.api import repositories
from app.database import create_database, initialize_database
from app.schemas.decision import DecisionCreate
from app.schemas.repository import RepositoryQuestionRequest
from app.services.code_context import ContextSource, RelatedContext
from app.services.decision_store import (
    QA_MEMORY_MAX_CONTEXT_BYTES,
    QA_MEMORY_MAX_DECISIONS,
    create_decision,
    relevant_decisions_for_qa,
)


class QAMemorySelectionTests(unittest.TestCase):
    def setUp(self):
        self.database = create_database("sqlite:///:memory:")
        initialize_database(self.database)
        self.session = self.database.session_factory()

    def tearDown(self):
        self.session.close()
        self.database.engine.dispose()

    def add(self, owner, repository, title, content, source_path=None):
        return create_decision(
            self.session,
            owner.lower(),
            repository.lower(),
            f"{owner}/{repository}",
            DecisionCreate(title=title, content=content, source_path=source_path),
        )

    def test_only_same_normalized_repository_decisions_are_returned(self):
        self.add("Owner", "Repo", "same repo", "same", "src/page.ts")
        self.add("Other", "Repo", "other owner", "must not leak", "src/page.ts")
        self.add("Owner", "OtherRepo", "other repository", "must not leak")

        result = relevant_decisions_for_qa(
            self.session, "owner", "repo", {"src/page.ts"}
        )

        self.assertEqual([item["title"] for item in result], ["same repo"])
        self.assertNotIn("must not leak", json.dumps(result))

    def test_matching_paths_precede_repository_wide_decisions(self):
        self.add("owner", "repo", "repository-wide", "global note")
        self.add("owner", "repo", "unrelated file", "unrelated", "src/other.ts")
        self.add("owner", "repo", "matching file", "path note", "src/page.ts")

        result = relevant_decisions_for_qa(
            self.session, "owner", "repo", {"src/page.ts", "src/helper.ts"}
        )
        repeated_result = relevant_decisions_for_qa(
            self.session, "owner", "repo", {"src/page.ts", "src/helper.ts"}
        )

        self.assertEqual(
            [item["title"] for item in result],
            ["matching file", "repository-wide", "unrelated file"],
        )
        self.assertEqual(result, repeated_result)

    def test_context_is_bounded_by_decision_count_and_serialized_utf8_size(self):
        for index in range(QA_MEMORY_MAX_DECISIONS + 3):
            self.add("owner", "repo", f"decision {index}", "x" * 4000)

        result = relevant_decisions_for_qa(self.session, "owner", "repo", set())
        encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("utf-8")

        self.assertLessEqual(len(result), QA_MEMORY_MAX_DECISIONS)
        self.assertLessEqual(len(encoded), QA_MEMORY_MAX_CONTEXT_BYTES)

    def test_empty_memory_returns_empty_context(self):
        self.assertEqual(
            relevant_decisions_for_qa(self.session, "owner", "repo", {"src/page.ts"}),
            [],
        )


class RelatedQAMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_readme_decision_reaches_dashboard_related_file_answer(self):
        database = create_database("sqlite:///:memory:")
        initialize_database(database)
        session = database.session_factory()
        try:
            create_decision(
                session,
                "ashtikasingh",
                "fitness_tracker",
                "ashtikasingh/Fitness_Tracker",
                DecisionCreate(
                    title="API migration plan",
                    content=(
                        "The application currently uses a local mock API and plans "
                        "a future Strapi integration."
                    ),
                    source_path="README.md",
                ),
            )
            question = RepositoryQuestionRequest(
                owner="ashtikasingh",
                repository="Fitness_Tracker",
                path="client/src/pages/Dashboard.tsx",
                ref="main",
                question="What did Developer Memory record about the API plan?",
            )
            context = RelatedContext(
                sources=[
                    ContextSource("F1", "client/src/pages/Dashboard.tsx", "dashboard", 9),
                    ContextSource("F2", "client/src/context/AppContext.tsx", "context", 7),
                    ContextSource("F3", "client/src/types/index.ts", "types", 5),
                    ContextSource("F4", "client/src/assets.ts", "assets", 4),
                ],
                complete=True,
                message=None,
            )
            http_request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/repositories/ask-related",
                    "headers": [],
                    "query_string": b"",
                    "server": ("testserver", 80),
                    "client": ("127.0.0.1", 12345),
                }
            )
            with (
                patch.object(repositories, "validate_gemini_configuration"),
                patch.object(
                    repositories,
                    "build_related_context",
                    new=AsyncMock(return_value=context),
                ),
                patch.object(
                    repositories,
                    "answer_about_sources",
                    new=AsyncMock(return_value="Developer Memory records a historical API plan."),
                ) as answer,
            ):
                response = await repositories.ask_about_related_files(
                    question, http_request, session
                )

            self.assertEqual(response.repository, "ashtikasingh/Fitness_Tracker")
            memory = answer.await_args.kwargs["memory_context"]
            self.assertEqual(len(memory), 1)
            self.assertEqual(memory[0]["source_path"], "README.md")
            self.assertIn("future Strapi integration", memory[0]["content"])
        finally:
            session.close()
            database.engine.dispose()


if __name__ == "__main__":
    unittest.main()
