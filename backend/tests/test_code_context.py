import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.schemas.repository import RepositoryTreeEntry
from app.services import code_context
from app.services.github import GitHubAPIError


def tree_entry(path, size=None):
    return RepositoryTreeEntry(path=path, type="blob", sha="test-sha", size=size)


class RelatedContextTests(unittest.IsolatedAsyncioTestCase):
    def setup_context(self, seed, files, tree, failures=None):
        failures = failures or {}

        async def fetch_file(owner, repository, path, ref=None):
            if path in failures:
                raise failures[path]
            content = files[path]
            return f"{owner}/{repository}", path, ref or "main", content, len(content.encode())

        return (
            patch.object(code_context, "fetch_public_file_content", side_effect=fetch_file),
            patch.object(code_context, "fetch_public_repository_tree", new=AsyncMock(return_value=(tree, False))),
        )

    def test_import_scanner_ignores_comments_strings_packages_and_dynamic_imports(self):
        source = (
            '// import "./commented";\n'
            'const sample = "import \'./string-value\'";\n'
            'import { value } from "./static";\n'
            'export { other } from "../reexport";\n'
            'import "package-name";\n'
            'const lazy = import("./dynamic");\n'
        )
        self.assertEqual(
            code_context._extract_relative_imports(source),
            ["./static", "../reexport"],
        )

    async def test_resolves_imports_reexports_and_deduplicates_files(self):
        seed = (
            'import { helper } from "./helper";\n'
            'export { shape } from "../shared/index";\n'
            'import { helper as again } from "./helper";\n'
            'import "package-name";\n'
            'const lazy = import("./dynamic");\n'
        )
        files = {
            "src/page.tsx": seed,
            "src/helper.ts": "export function helper() { return 1; }",
            "shared/index.ts": "export const shape = {};",
            "src/dynamic.ts": "export const lazy = true;",
        }
        tree = [tree_entry(path, len(content)) for path, content in files.items()]
        file_patch, tree_patch = self.setup_context(seed, files, tree)
        with file_patch, tree_patch:
            context = await code_context.build_related_context("owner", "repo", "src/page.tsx", "main")

        self.assertEqual([source.path for source in context.sources], [
            "src/page.tsx", "src/helper.ts", "shared/index.ts"
        ])
        self.assertEqual([source.source_id for source in context.sources], ["F1", "F2", "F3"])
        self.assertTrue(context.complete)

    async def test_unresolved_and_unsafe_imports_are_omitted_and_mark_incomplete(self):
        seed = 'import "../../../../outside";\nimport "./missing";'
        files = {"src/page.ts": seed, "outside.ts": "must not fetch"}
        tree = [tree_entry(path, len(content)) for path, content in files.items()]
        file_patch, tree_patch = self.setup_context(seed, files, tree)
        with file_patch as file_mock, tree_patch:
            context = await code_context.build_related_context("owner", "repo", "src/page.ts", "main")

        self.assertEqual([source.path for source in context.sources], ["src/page.ts"])
        self.assertFalse(context.complete)
        self.assertIn("could not be resolved", context.message)
        self.assertEqual(
            [call.args[2] for call in file_mock.call_args_list], ["src/page.ts"]
        )

    async def test_related_not_found_is_skipped_and_marks_context_incomplete(self):
        seed = 'import "./missing";'
        files = {"src/page.ts": seed}
        tree = [tree_entry("src/page.ts"), tree_entry("src/missing.ts")]
        failure = GitHubAPIError("repository_not_found", "safe", 404)
        file_patch, tree_patch = self.setup_context(
            seed, files, tree, {"src/missing.ts": failure}
        )
        with file_patch, tree_patch:
            context = await code_context.build_related_context("owner", "repo", "src/page.ts", "main")

        self.assertFalse(context.complete)
        self.assertEqual(len(context.sources), 1)
        self.assertIn("unavailable or unsupported", context.message)

    async def test_related_file_size_limit_skips_candidate(self):
        seed = 'import "./large";'
        files = {"src/page.ts": seed, "src/large.ts": "x"}
        tree = [tree_entry("src/page.ts", len(seed)), tree_entry("src/large.ts", code_context.MAX_CONTEXT_BYTES)]
        file_patch, tree_patch = self.setup_context(seed, files, tree)
        with file_patch as file_mock, tree_patch:
            context = await code_context.build_related_context("owner", "repo", "src/page.ts", "main")

        self.assertEqual(len(context.sources), 1)
        self.assertFalse(context.complete)
        self.assertIn("per-file size limit", context.message)
        self.assertEqual(file_mock.call_count, 1)

    async def test_total_context_limit_skips_related_file(self):
        seed = 'import "./related";\nimport "./last";'
        selected = seed + "s" * (128 * 1024 - len(seed))
        related = "r" * (128 * 1024)
        files = {
            "src/page.ts": selected,
            "src/related.ts": related,
            "src/last.ts": "export {};",
        }
        tree = [tree_entry(path) for path in files]
        file_patch, tree_patch = self.setup_context(seed, files, tree)
        with file_patch, tree_patch:
            context = await code_context.build_related_context("owner", "repo", "src/page.ts", "main")

        self.assertEqual(
            [source.path for source in context.sources],
            ["src/page.ts", "src/last.ts"],
        )
        self.assertFalse(context.complete)
        self.assertIn("total source context limit", context.message)
        self.assertNotIn("src/related.ts", [source.path for source in context.sources])

    async def test_four_file_limit_and_truncated_tree_are_reported(self):
        paths = [f"src/file{index}.ts" for index in range(5)]
        seed = "\n".join(f'import "./file{index}";' for index in range(5))
        files = {"src/page.ts": seed, **{path: "export {};" for path in paths}}
        tree = [tree_entry(path) for path in files]
        file_patch, tree_patch = self.setup_context(seed, files, tree)
        tree_patch = patch.object(
            code_context,
            "fetch_public_repository_tree",
            new=AsyncMock(return_value=(tree, True)),
        )
        with file_patch, tree_patch:
            context = await code_context.build_related_context("owner", "repo", "src/page.ts", "main")

        self.assertEqual(len(context.sources), code_context.MAX_CONTEXT_FILES)
        self.assertFalse(context.complete)
        self.assertIn("truncated", context.message)
        self.assertIn("file limit", context.message)

    async def test_discovery_deadline_returns_safe_github_timeout(self):
        async def delayed_fetch(*args, **kwargs):
            await asyncio.sleep(0.02)
            return "owner/repo", "src/page.ts", "main", "TOP_SECRET_SOURCE_VALUE", 23

        with (
            patch.object(code_context, "CONTEXT_DEADLINE_SECONDS", 0.001),
            patch.object(code_context, "fetch_public_file_content", side_effect=delayed_fetch),
        ):
            with self.assertRaises(GitHubAPIError) as raised:
                await code_context.build_related_context("owner", "repo", "src/page.ts", "main")

        self.assertEqual(raised.exception.status_code, 504)
        self.assertNotIn("TOP_SECRET_SOURCE_VALUE", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
