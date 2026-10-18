"use client";

import { useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { parseMarkdown, type MarkdownBlock, type MarkdownInline } from "@/lib/markdown";

type RepositoryMetadata = {
  name: string;
  full_name: string;
  html_url: string;
  description: string | null;
  default_branch: string;
  stargazers_count: number;
};

type RepositoryTreeEntry = {
  path: string;
  type: "blob" | "tree" | "commit";
  sha: string;
  size: number | null;
};

type RepositoryInspection = {
  repository: RepositoryMetadata;
  tree: RepositoryTreeEntry[];
  tree_complete: boolean;
  tree_truncated: boolean;
  tree_message: string | null;
};

type ErrorResponse = {
  error?: {
    message?: string;
    retry_after_seconds?: number;
  };
};

type RepositoryFile = {
  repository: string;
  path: string;
  ref: string;
  content: string;
  size_bytes: number;
};

type RepositoryAnswer = {
  repository: string;
  path: string;
  answer: string;
};

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

function renderInlineMarkdown(nodes: MarkdownInline[], keyPrefix: string): ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${keyPrefix}-${index}`;
    switch (node.type) {
      case "text":
        return node.text;
      case "code":
        return <code key={key}>{node.text}</code>;
      case "strong":
        return <strong key={key}>{renderInlineMarkdown(node.children, key)}</strong>;
      case "emphasis":
        return <em key={key}>{renderInlineMarkdown(node.children, key)}</em>;
    }
  });
}

function renderMarkdownBlock(block: MarkdownBlock, index: number): ReactNode {
  const key = `answer-block-${index}`;
  switch (block.type) {
    case "paragraph":
      return <p key={key}>{renderInlineMarkdown(block.children, key)}</p>;
    case "heading": {
      const children = renderInlineMarkdown(block.children, key);
      if (block.level === 1) return <h1 key={key}>{children}</h1>;
      if (block.level === 2) return <h2 key={key}>{children}</h2>;
      return <h3 key={key}>{children}</h3>;
    }
    case "unordered-list":
      return <ul key={key}>{block.items.map((item, itemIndex) => (
        <li key={`${key}-item-${itemIndex}`}>{renderInlineMarkdown(item, `${key}-item-${itemIndex}`)}</li>
      ))}</ul>;
    case "ordered-list":
      return <ol key={key} start={block.start}>{block.items.map((item, itemIndex) => (
        <li key={`${key}-item-${itemIndex}`}>{renderInlineMarkdown(item, `${key}-item-${itemIndex}`)}</li>
      ))}</ol>;
    case "code-block":
      return <pre key={key}><code>{block.text}</code></pre>;
    case "horizontal-rule":
      return <hr key={key} />;
  }
}

function MarkdownAnswer({ content }: { content: string }) {
  return <div className="answer-text">{parseMarkdown(content).map(renderMarkdownBlock)}</div>;
}

function GitHubIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 6v-3.9a3.4 3.4 0 0 0-.9-2.6c3-.3 6.1-1.5 6.1-6.8a5.3 5.3 0 0 0-1.4-3.7 4.9 4.9 0 0 0-.1-3.7s-1.2-.4-3.9 1.4a13.5 13.5 0 0 0-7.1 0C5 1 3.8 1.4 3.8 1.4a4.9 4.9 0 0 0-.1 3.7 5.3 5.3 0 0 0-1.4 3.7c0 5.3 3.1 6.5 6.1 6.8a3.4 3.4 0 0 0-.9 2.6V22" transform="translate(2 1) scale(.84)" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TreeIcon({ type }: { type: RepositoryTreeEntry["type"] }) {
  if (type === "tree") {
    return (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M3.5 6.5h6l2 2h9v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M3.5 9h17" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    );
  }

  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 3.5h8l4 4v13H6z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M14 3.5v4h4M9 12h6m-6 3h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function FileTree({
  entries,
  selectedPath,
  disabled,
  onSelect,
}: {
  entries: RepositoryTreeEntry[];
  selectedPath: string | null;
  disabled: boolean;
  onSelect: (entry: RepositoryTreeEntry) => void;
}) {
  if (entries.length === 0) {
    return <p className="tree-empty">GitHub returned no files for this repository.</p>;
  }

  return (
    <ul className="tree-list" aria-label="Repository file tree">
      {entries.map((entry) => {
        const segments = entry.path.split("/");
        const depth = segments.length - 1;
        const label = segments[segments.length - 1];

        return (
          <li
            key={`${entry.path}:${entry.sha}`}
          >
            <button
              type="button"
              className={`tree-entry${entry.type === "tree" ? " tree-directory" : ""}${selectedPath === entry.path ? " selected" : ""}`}
              style={{ "--tree-depth": depth } as CSSProperties & { "--tree-depth": number }}
              title={entry.path}
              disabled={entry.type !== "blob" || disabled}
              aria-pressed={selectedPath === entry.path}
              onClick={() => onSelect(entry)}
            >
              <span className="tree-entry-icon"><TreeIcon type={entry.type} /></span>
              <span className="tree-entry-name">{label}</span>
              {entry.type === "commit" && <span className="tree-entry-type">submodule</span>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export default function RepositoryImportPanel() {
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [inspection, setInspection] = useState<RepositoryInspection | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [sourceFile, setSourceFile] = useState<RepositoryFile | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [isLoadingSource, setIsLoadingSource] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<RepositoryAnswer | null>(null);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [isAsking, setIsAsking] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setInspection(null);
    setErrorMessage(null);
    setSelectedPath(null);
    setSourceFile(null);
    setSourceError(null);
    setAnswer(null);
    setQuestionError(null);
    setQuestion("");

    try {
      const response = await fetch(`${API_BASE_URL}/api/repositories/inspect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository_url: repositoryUrl }),
        cache: "no-store",
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ErrorResponse | null;
        setErrorMessage(
          body?.error?.message ?? "The repository could not be inspected. Check the URL and try again.",
        );
        return;
      }

      const result = (await response.json()) as RepositoryInspection;
      setInspection(result);
    } catch {
      setErrorMessage(
        "Could not reach DevPilot's API. Make sure the backend is running at http://localhost:8000 and try again.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSelectFile(entry: RepositoryTreeEntry) {
    if (!inspection || entry.type !== "blob") return;
    const [owner, repository] = inspection.repository.full_name.split("/", 2);
    setSelectedPath(entry.path);
    setSourceFile(null);
    setAnswer(null);
    setQuestionError(null);
    setSourceError(null);
    setIsLoadingSource(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/repositories/file`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          owner,
          repository,
          path: entry.path,
          ref: inspection.repository.default_branch,
        }),
        cache: "no-store",
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ErrorResponse | null;
        setSourceError(body?.error?.message ?? "Could not retrieve this source file.");
        return;
      }
      setSourceFile((await response.json()) as RepositoryFile);
    } catch {
      setSourceError("Could not reach DevPilot’s API. Check that the backend is running.");
    } finally {
      setIsLoadingSource(false);
    }
  }

  async function handleAskQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!inspection || !sourceFile || !question.trim()) return;
    const [owner, repository] = inspection.repository.full_name.split("/", 2);
    setIsAsking(true);
    setQuestionError(null);
    setAnswer(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/repositories/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          owner,
          repository,
          path: sourceFile.path,
          ref: sourceFile.ref,
          question: question.trim(),
        }),
        cache: "no-store",
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ErrorResponse | null;
        setQuestionError(body?.error?.message ?? "DevPilot could not answer this question.");
        return;
      }
      setAnswer((await response.json()) as RepositoryAnswer);
    } catch {
      setQuestionError("Could not reach DevPilot’s API. Check that the backend is running.");
    } finally {
      setIsAsking(false);
    }
  }

  const isTreeIncomplete = inspection !== null && (
    inspection.tree_truncated || !inspection.tree_complete
  );

  return (
    <section className="import-panel" aria-labelledby="import-title">
      <div className="import-copy">
        <div className="import-kicker"><span className="github-badge"><GitHubIcon /></span><span>START WITH A REPOSITORY</span></div>
        <h2 id="import-title">Bring your codebase<br className="desktop-break" /> into focus.</h2>
        <p>Connect a public GitHub repository to see its metadata and file structure.</p>
        <div className="import-note"><span className="note-dot" />Public repositories only · no cloning</div>
      </div>

      <div className="import-form-wrap">
        <label className="input-label" htmlFor="repository-url">PUBLIC REPOSITORY URL</label>
        <form className="import-form" onSubmit={handleSubmit}>
          <span className="input-github"><GitHubIcon /></span>
          <input
            id="repository-url"
            type="text"
            inputMode="url"
            autoCapitalize="none"
            autoComplete="url"
            spellCheck={false}
            placeholder="https://github.com/owner/repository"
            value={repositoryUrl}
            onChange={(event) => setRepositoryUrl(event.target.value)}
            aria-describedby="import-status"
            aria-invalid={errorMessage ? true : undefined}
          />
          <button type="submit" disabled={isLoading || repositoryUrl.trim().length === 0}>
            {isLoading ? <><span className="button-spinner" />Inspecting</> : <>Inspect <span aria-hidden="true">→</span></>}
          </button>
        </form>
        <p className="form-caption" id="import-status">Public repositories only <span>·</span> Uses GitHub&apos;s public REST API</p>
        {errorMessage && <p className="import-error" role="alert">{errorMessage}</p>}
        {isLoading && <p className="import-loading" role="status">Fetching repository metadata and file tree…</p>}
        {!inspection && !errorMessage && !isLoading && (
          <div className="repo-example"><span className="repo-example-icon"><GitHubIcon size={16} /></span><span>Paste a public repository URL to inspect its files</span><span className="repo-example-badge">PUBLIC</span></div>
        )}
      </div>

      {inspection && (
        <div className="repository-result" aria-live="polite">
          <div className="repository-summary">
            <div className="repository-heading">
              <span className="repo-result-icon"><GitHubIcon size={17} /></span>
              <div className="repository-title-wrap">
                <a className="repository-name" href={inspection.repository.html_url} target="_blank" rel="noreferrer">
                  {inspection.repository.full_name}
                </a>
                <p>{inspection.repository.description || "No description provided."}</p>
              </div>
              <span className="repository-branch">{inspection.repository.default_branch}</span>
            </div>
            <div className="tree-heading-row">
              <div><span className="section-eyebrow">REPOSITORY CONTENTS</span><h3>File tree</h3></div>
              <span className={`tree-status${isTreeIncomplete ? " incomplete" : " complete"}`}>
                {isTreeIncomplete ? "INCOMPLETE TREE" : "COMPLETE TREE"}
              </span>
            </div>
            {isTreeIncomplete && (
              <div className="tree-warning" role="status">
                <span className="tree-warning-mark">!</span>
                <span>{inspection.tree_message || "GitHub truncated this tree. The entries below are incomplete and may omit files."}</span>
              </div>
            )}
          </div>
          <div className={`tree-scroll${isTreeIncomplete ? " tree-scroll-incomplete" : ""}`}>
            <FileTree
              entries={inspection.tree}
              selectedPath={selectedPath}
              disabled={isLoadingSource}
              onSelect={handleSelectFile}
            />
          </div>
          <p className="tree-footnote">Select a file to view its public source. DevPilot does not clone or execute repository code.</p>

          <section className="source-section" aria-labelledby="source-title">
            <div className="source-heading">
              <div><span className="section-eyebrow">CODEBASE Q&amp;A</span><h3 id="source-title">Selected source file</h3></div>
              {sourceFile && <span className="source-size">{sourceFile.size_bytes.toLocaleString()} bytes</span>}
            </div>
            {!selectedPath && <p className="source-placeholder">Choose a source file from the tree to inspect its contents and ask a question.</p>}
            {isLoadingSource && <p className="import-loading" role="status">Retrieving source file from GitHub…</p>}
            {sourceError && <p className="import-error" role="alert">{sourceError}</p>}
            {sourceFile && (
              <>
                <p className="source-path"><span>FILE</span>{sourceFile.repository}/{sourceFile.path}</p>
                <pre className="source-viewer" aria-label={`Source code for ${sourceFile.path}`}><code>{sourceFile.content}</code></pre>
                <form className="question-form" onSubmit={handleAskQuestion}>
                  <label className="input-label" htmlFor="file-question">ASK ABOUT THIS FILE</label>
                  <textarea
                    id="file-question"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="What does this function do?"
                    maxLength={2000}
                    rows={3}
                    required
                    aria-describedby="question-limit"
                  />
                  <div className="question-actions">
                    <span id="question-limit">Up to 2,000 characters · Answers use this file only</span>
                    <button type="submit" disabled={isAsking || !question.trim()}>
                      {isAsking ? <><span className="button-spinner" />Asking</> : <>Ask Gemini <span aria-hidden="true">→</span></>}
                    </button>
                  </div>
                </form>
                {questionError && <p className="import-error" role="alert">{questionError}</p>}
                {isAsking && <p className="import-loading" role="status">Gemini is reviewing the selected file…</p>}
                {answer && (
                  <div className="answer-card" aria-live="polite">
                    <span className="section-eyebrow">ANSWER BASED ON</span>
                    <p className="answer-source">{answer.repository}/{answer.path}</p>
                    <MarkdownAnswer content={answer.answer} />
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}

      <div className="import-decoration" aria-hidden="true"><span /><span /><span /><span /><span /></div>
    </section>
  );
}
