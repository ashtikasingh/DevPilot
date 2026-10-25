"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  createDecision,
  deleteDecision,
  listDecisions,
  updateDecision,
  type Decision,
} from "@/lib/developer-memory";

type DeveloperMemoryPanelProps = {
  repository: { full_name: string } | null;
  selectedPath: string | null;
};

type DecisionListState = {
  repository: string | null;
  decisions: Decision[];
  loading: boolean;
  error: string | null;
};

type Feedback = { repository: string; kind: "success" | "error"; message: string } | null;

function splitRepository(repository: string): [string, string] | null {
  const separator = repository.indexOf("/");
  if (separator < 1 || separator === repository.length - 1) return null;
  return [repository.slice(0, separator), repository.slice(separator + 1)];
}

export default function DeveloperMemoryPanel({
  repository,
  selectedPath,
}: DeveloperMemoryPanelProps) {
  const repositoryName = repository?.full_name ?? null;
  const repositoryParts = repositoryName ? splitRepository(repositoryName) : null;
  const currentRepository = useRef<string | null>(repositoryName);
  const loadIdentity = useRef(0);
  const mutationIdentity = useRef(0);

  const [listState, setListState] = useState<DecisionListState>({
    repository: repositoryName,
    decisions: [],
    loading: Boolean(repositoryName),
    error: null,
  });
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sourcePathOverride, setSourcePathOverride] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const sourcePath = sourcePathOverride ?? selectedPath ?? "";

  function invalidatePendingRequests() {
    ++loadIdentity.current;
    ++mutationIdentity.current;
  }

  async function loadRepositoryDecisions(scope: string): Promise<void> {
    const parts = splitRepository(scope);
    if (!parts) {
      setListState({ repository: scope, decisions: [], loading: false, error: "The selected repository identity is invalid." });
      return;
    }
    const requestId = ++loadIdentity.current;
    setListState({ repository: scope, decisions: [], loading: true, error: null });
    try {
      const result = await listDecisions(parts[0], parts[1]);
      if (loadIdentity.current === requestId) {
        setListState({ repository: scope, decisions: result.decisions, loading: false, error: null });
      }
    } catch (error) {
      if (loadIdentity.current === requestId) {
        setListState({
          repository: scope,
          decisions: [],
          loading: false,
          error: error instanceof Error ? error.message : "Could not load shared decisions.",
        });
      }
    }
  }

  useEffect(() => {
    if (!repositoryName) return;
    const parts = splitRepository(repositoryName);
    if (!parts) return;
    const requestId = ++loadIdentity.current;
    void listDecisions(parts[0], parts[1]).then((result) => {
      if (loadIdentity.current === requestId) {
        setListState({ repository: repositoryName, decisions: result.decisions, loading: false, error: null });
      }
    }).catch((error: unknown) => {
      if (loadIdentity.current === requestId) {
        setListState({
          repository: repositoryName,
          decisions: [],
          loading: false,
          error: error instanceof Error ? error.message : "Could not load shared decisions.",
        });
      }
    });

    return invalidatePendingRequests;
  }, [repositoryName]);

  function beginEditing(decision: Decision) {
    setEditingId(decision.id);
    setTitle(decision.title);
    setContent(decision.content);
    setSourcePathOverride(decision.source_path ?? "");
    setFeedback(null);
    setConfirmingDeleteId(null);
  }

  function cancelEditing() {
    setEditingId(null);
    setTitle("");
    setContent("");
    setSourcePathOverride(null);
  }

  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!repositoryName || !repositoryParts || !title.trim() || !content.trim() || isSaving) return;
    const scope = repositoryName;
    const requestId = ++mutationIdentity.current;
    const payload = {
      title: title.trim(),
      content: content.trim(),
      source_path: sourcePath.trim() || null,
    };
    setIsSaving(true);
    setFeedback(null);
    try {
      if (editingId) {
        await updateDecision(repositoryParts[0], repositoryParts[1], editingId, payload);
      } else {
        await createDecision(repositoryParts[0], repositoryParts[1], payload);
      }
      if (currentRepository.current !== scope || mutationIdentity.current !== requestId) return;
      setFeedback({ repository: scope, kind: "success", message: editingId ? "Decision updated." : "Decision added." });
      setEditingId(null);
      setTitle("");
      setContent("");
      setSourcePathOverride(null);
      await loadRepositoryDecisions(scope);
    } catch (error) {
      if (currentRepository.current === scope && mutationIdentity.current === requestId) {
        setFeedback({
          repository: scope,
          kind: "error",
          message: error instanceof Error ? error.message : "Could not save this decision.",
        });
      }
    } finally {
      if (currentRepository.current === scope && mutationIdentity.current === requestId) setIsSaving(false);
    }
  }

  async function confirmDelete(decision: Decision) {
    if (!repositoryName || !repositoryParts || isSaving) return;
    const scope = repositoryName;
    const requestId = ++mutationIdentity.current;
    setIsSaving(true);
    setFeedback(null);
    try {
      await deleteDecision(repositoryParts[0], repositoryParts[1], decision.id);
      if (currentRepository.current !== scope || mutationIdentity.current !== requestId) return;
      setConfirmingDeleteId(null);
      setFeedback({ repository: scope, kind: "success", message: "Decision deleted." });
      await loadRepositoryDecisions(scope);
    } catch (error) {
      if (currentRepository.current === scope && mutationIdentity.current === requestId) {
        setFeedback({
          repository: scope,
          kind: "error",
          message: error instanceof Error ? error.message : "Could not delete this decision.",
        });
      }
    } finally {
      if (currentRepository.current === scope && mutationIdentity.current === requestId) setIsSaving(false);
    }
  }

  const hasSelectedRepository = Boolean(repositoryName && repositoryParts);
  const decisions = listState.repository === repositoryName ? listState.decisions : [];
  const isLoading = hasSelectedRepository && listState.repository !== repositoryName
    ? true
    : listState.repository === repositoryName && listState.loading;
  const listError = listState.repository === repositoryName ? listState.error : null;

  return (
    <section className="developer-memory-panel" id="memory" aria-labelledby="developer-memory-title">
      <header className="memory-heading">
        <div>
          <span className="section-eyebrow">DEVELOPER MEMORY</span>
          <h3 id="developer-memory-title">Repository decisions</h3>
        </div>
        {repositoryName && <span className="memory-repository">{repositoryName}</span>}
      </header>

      <p className="memory-shared-notice">
        Shared memory for public repositories. Do not store secrets, credentials, or private information. Anyone using DevPilot for this repository may read, add, edit, or delete these decisions.
      </p>

      {!hasSelectedRepository && (
        <p className="memory-selection-hint" role="status">Inspect a public repository first to view or manage its shared decisions.</p>
      )}
      {hasSelectedRepository && isLoading && <p className="import-loading" role="status">Loading shared decisions…</p>}
      {hasSelectedRepository && listError && <p className="import-error" role="alert">{listError}</p>}
      {hasSelectedRepository && !isLoading && !listError && decisions.length === 0 && (
        <p className="memory-empty">No decisions saved for this repository yet.</p>
      )}

      <form className="memory-form" onSubmit={submitDecision}>
        <h4>{editingId ? "Edit decision" : "Add a decision"}</h4>
        <label htmlFor="memory-title">Title</label>
        <input
          id="memory-title"
          value={title}
          maxLength={120}
          required
          disabled={!hasSelectedRepository || isSaving}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="A short, searchable decision"
        />
        <label htmlFor="memory-content">Decision</label>
        <textarea
          id="memory-content"
          value={content}
          maxLength={4000}
          rows={4}
          required
          disabled={!hasSelectedRepository || isSaving}
          onChange={(event) => setContent(event.target.value)}
          placeholder="What was decided, and why?"
        />
        <div className="memory-source-input">
          <label htmlFor="memory-source-path">Source path <span>(optional)</span></label>
          <div>
            <input
              id="memory-source-path"
              value={sourcePath}
              maxLength={1024}
              disabled={!hasSelectedRepository || isSaving}
              onChange={(event) => {
                setSourcePathOverride(event.target.value);
              }}
              placeholder="src/path/to/file.ts"
            />
            {selectedPath && !editingId && <button type="button" disabled={!hasSelectedRepository || isSaving} onClick={() => {
              setSourcePathOverride(null);
            }}>Use selected file</button>}
            {sourcePath && <button type="button" disabled={!hasSelectedRepository || isSaving} onClick={() => {
              setSourcePathOverride("");
            }}>Clear</button>}
          </div>
        </div>
        <div className="memory-form-actions">
          {editingId && <button type="button" className="memory-secondary-button" disabled={isSaving} onClick={cancelEditing}>Cancel</button>}
          <button type="submit" disabled={!hasSelectedRepository || isSaving || !title.trim() || !content.trim()}>
            {isSaving ? "Saving…" : editingId ? "Save changes" : "Add decision"}
          </button>
        </div>
      </form>

      {feedback?.repository === repositoryName && (
        <p className={`memory-feedback ${feedback.kind}`} role={feedback.kind === "error" ? "alert" : "status"}>{feedback.message}</p>
      )}

      {hasSelectedRepository && decisions.length > 0 && (
        <ul className="memory-decision-list" aria-label="Shared repository decisions">
          {decisions.map((decision) => (
            <li key={decision.id} className="memory-decision">
              {editingId === decision.id ? (
                <p className="memory-editing-indicator">Editing this decision above</p>
              ) : (
                <>
                  <div className="memory-decision-heading">
                    <h4>{decision.title}</h4>
                    {decision.source_path && <code>{decision.source_path}</code>}
                  </div>
                  <p className="memory-decision-content">{decision.content}</p>
                  <div className="memory-decision-actions">
                    <button type="button" disabled={isSaving || Boolean(editingId)} onClick={() => beginEditing(decision)}>Edit</button>
                    {confirmingDeleteId === decision.id ? (
                      <>
                        <span>Delete this shared decision?</span>
                        <button type="button" disabled={isSaving} onClick={() => void confirmDelete(decision)}>Confirm delete</button>
                        <button type="button" disabled={isSaving} onClick={() => setConfirmingDeleteId(null)}>Cancel</button>
                      </>
                    ) : (
                      <button type="button" disabled={isSaving || Boolean(editingId)} onClick={() => {
                        setConfirmingDeleteId(decision.id);
                        setFeedback(null);
                      }}>Delete</button>
                    )}
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
