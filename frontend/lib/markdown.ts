export type MarkdownInline =
  | { type: "text" | "code"; text: string }
  | { type: "strong" | "emphasis"; children: MarkdownInline[] };

export type MarkdownBlock =
  | { type: "paragraph" | "heading"; level?: number; children: MarkdownInline[] }
  | { type: "unordered-list"; items: MarkdownInline[][] }
  | { type: "ordered-list"; start: number; items: MarkdownInline[][] }
  | { type: "code-block"; text: string }
  | { type: "horizontal-rule" };

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  lt: "<",
  quot: '"',
};

const INLINE_TOKEN_PATTERN = /(`+)(.+?)\1|\*\*(.+?)\*\*|__(.+?)__|\*([^*\n]+)\*|_([^_\n]+)_|\\([\\`*_{}#+.!|>~-])|&(amp|apos|gt|lt|quot|#39|#\d{1,7}|#x[\da-f]+);/gi;
const FENCED_CODE_PATTERN = /^\s*(```+|~~~+)/;
const HORIZONTAL_RULE_PATTERN = /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})[ \t]*$/;
const ESCAPED_DASH_RULE_PATTERN = /^ {0,3}\\{1,2}-(?:[ \t]*-){2,}[ \t]*$/;

function decodeMarkdownEntity(entity: string): string {
  const name = entity.slice(1, -1);
  if (name in NAMED_ENTITIES) return NAMED_ENTITIES[name];
  if (name === "#39") return "'";

  const numeric = name.match(/^#(x[\da-f]+|\d+)$/i)?.[1];
  if (!numeric) return entity;
  const codePoint = numeric[0].toLowerCase() === "x"
    ? Number.parseInt(numeric.slice(1), 16)
    : Number.parseInt(numeric, 10);
  if (!Number.isInteger(codePoint) || codePoint < 0 || codePoint > 0x10ffff) return entity;
  try {
    return String.fromCodePoint(codePoint);
  } catch {
    return entity;
  }
}

function decodeTextEntities(text: string): string {
  return text.replace(
    /&(amp|apos|gt|lt|quot|#39|#\d{1,7}|#x[\da-f]+);/gi,
    (entity) => decodeMarkdownEntity(entity),
  );
}

export function parseInlineMarkdown(text: string): MarkdownInline[] {
  const nodes: MarkdownInline[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  const tokenPattern = new RegExp(INLINE_TOKEN_PATTERN.source, INLINE_TOKEN_PATTERN.flags);

  while ((match = tokenPattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push({ type: "text", text: decodeTextEntities(text.slice(cursor, match.index)) });
    }

    if (match[1]) {
      nodes.push({ type: "code", text: match[2] });
    } else if (match[3] || match[4]) {
      nodes.push({ type: "strong", children: parseInlineMarkdown(match[3] ?? match[4]) });
    } else if (match[5] || match[6]) {
      nodes.push({ type: "emphasis", children: parseInlineMarkdown(match[5] ?? match[6]) });
    } else if (match[7]) {
      nodes.push({ type: "text", text: match[7] });
    } else if (match[8]) {
      nodes.push({ type: "text", text: decodeMarkdownEntity(match[0]) });
    }
    cursor = tokenPattern.lastIndex;
  }

  if (cursor < text.length) {
    nodes.push({ type: "text", text: decodeTextEntities(text.slice(cursor)) });
  }
  return nodes;
}

function isHorizontalRule(line: string): boolean {
  return HORIZONTAL_RULE_PATTERN.test(line) || ESCAPED_DASH_RULE_PATTERN.test(line);
}

export function parseMarkdown(content: string): MarkdownBlock[] {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(FENCED_CODE_PATTERN);
    if (fence) {
      const codeLines: string[] = [];
      const fenceCharacter = fence[1][0];
      const fenceLength = fence[1].length;
      index += 1;
      while (index < lines.length) {
        const closingFence = lines[index].match(/^\s*(```+|~~~+)/);
        if (closingFence && closingFence[1][0] === fenceCharacter && closingFence[1].length >= fenceLength) {
          index += 1;
          break;
        }
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code-block", text: codeLines.join("\n") });
      continue;
    }

    if (isHorizontalRule(line)) {
      blocks.push({ type: "horizontal-rule" });
      index += 1;
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      blocks.push({
        type: "heading",
        level: Math.min(heading[1].length, 3),
        children: parseInlineMarkdown(heading[2]),
      });
      index += 1;
      continue;
    }

    const unorderedItem = line.match(/^\s*[-*+]\s+(.+)$/);
    const orderedItem = line.match(/^\s*(\d+)[.)]\s+(.+)$/);
    if (unorderedItem || orderedItem) {
      const ordered = Boolean(orderedItem);
      const items: MarkdownInline[][] = [];
      while (index < lines.length) {
        const item = ordered
          ? lines[index].match(/^\s*\d+[.)]\s+(.+)$/)
          : lines[index].match(/^\s*[-*+]\s+(.+)$/);
        if (!item) break;
        items.push(parseInlineMarkdown(item[1]));
        index += 1;
      }
      blocks.push(ordered
        ? { type: "ordered-list", start: Number(orderedItem?.[1] ?? 1), items }
        : { type: "unordered-list", items });
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !FENCED_CODE_PATTERN.test(lines[index])
      && !HORIZONTAL_RULE_PATTERN.test(lines[index])
      && !ESCAPED_DASH_RULE_PATTERN.test(lines[index])
      && !/^\s{0,3}#{1,6}\s+/.test(lines[index])
      && !/^\s*[-*+]\s+/.test(lines[index])
      && !/^\s*\d+[.)]\s+/.test(lines[index])
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: "paragraph", children: parseInlineMarkdown(paragraphLines.join(" ")) });
  }

  return blocks;
}
