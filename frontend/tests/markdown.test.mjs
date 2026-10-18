import assert from "node:assert/strict";
import test from "node:test";

import { parseInlineMarkdown, parseMarkdown } from "../lib/markdown.ts";

test("renders the reproduced escaped horizontal divider as a rule", () => {
  const oneBackslash = String.raw`\---`;
  const twoBackslashes = String.raw`\\---`;

  assert.deepEqual(parseMarkdown(oneBackslash), [{ type: "horizontal-rule" }]);
  assert.deepEqual(parseMarkdown(twoBackslashes), [{ type: "horizontal-rule" }]);
});

test("recognizes dash, asterisk, and underscore horizontal rules", () => {
  assert.deepEqual(parseMarkdown("---\n***\n___"), [
    { type: "horizontal-rule" },
    { type: "horizontal-rule" },
    { type: "horizontal-rule" },
  ]);
});

test("keeps horizontal-rule-looking lines inside fenced code as code", () => {
  assert.deepEqual(parseMarkdown("```tsx\n---\n***\n___\n```"), [
    { type: "code-block", text: "---\n***\n___" },
  ]);
});

test("parses headings, paragraphs, lists, and inline formatting", () => {
  const blocks = parseMarkdown(
    "## Summary\n\nPlain **bold** and *emphasis* with `code`.\n\n2. First\n3. Second\n\n- One\n- Two",
  );

  assert.deepEqual(blocks.map((block) => block.type), [
    "heading",
    "paragraph",
    "ordered-list",
    "unordered-list",
  ]);
  assert.equal(blocks[0].level, 2);
  assert.equal(blocks[2].start, 2);
  assert.deepEqual(blocks[1].children.map((node) => node.type), [
    "text",
    "strong",
    "text",
    "emphasis",
    "text",
    "code",
    "text",
  ]);
});

test("preserves escaped punctuation and only decodes supported entities in prose", () => {
  const escaped = parseInlineMarkdown(String.raw`\*literal\* &lt;tag&gt; `);
  assert.equal(escaped.map((node) => node.type === "text" ? node.text : "").join(""), "*literal* <tag> ");

  const codeAndEntity = parseInlineMarkdown("`&lt;` &lt;");
  assert.deepEqual(codeAndEntity[0], { type: "code", text: "&lt;" });
  assert.equal(
    codeAndEntity.slice(1).map((node) => node.type === "text" ? node.text : "").join(""),
    " <",
  );
});
