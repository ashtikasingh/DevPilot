# DevPilot

## Project Overview

DevPilot is a hackathon-stage developer workspace for understanding public GitHub repositories. It retrieves repository metadata and source files through the GitHub REST API, lets you ask Gemini questions about source code, and keeps repository-specific implementation decisions in Developer Memory. DevPilot does not clone repositories or execute repository code.

## Implemented Features

- **Public repository inspection:** Enter a public GitHub repository URL to view its metadata and file tree. GitHub tree truncation is reported rather than presented as complete.
- **Single-file Q&A:** Select a supported source file and ask questions about its contents. Answers can include citations to source line numbers; the backend checks citation syntax and ranges against the supplied source, but does not verify that a cited line semantically supports a claim.
- **Related-file Q&A:** Optionally include direct relative JavaScript/TypeScript imports and re-exports from the selected file. Discovery is bounded to the selected file plus at most three related files. Included sources receive independent IDs and line numbering, and context coverage is reported when files cannot be resolved or limits are reached.
- **Developer Memory:** Save, list, edit, and delete decisions scoped to a public repository. Repository identity is verified using GitHub metadata. Decisions are shared with anyone using DevPilot for that repository; they are not private or user-specific.
- **Memory-assisted Q&A:** Single-file and related-file Q&A can receive a small, bounded selection of saved decisions from the same repository as historical context. Exact source-path matches are preferred, followed by repository-wide and other same-repository decisions. A saved decision is not proof of current code behavior: current-code claims still require code citations, and historical memory does not receive source citations.

## Tech Stack

- **Frontend:** Next.js 16 App Router, React 19, TypeScript, and Tailwind CSS 4.
- **Backend:** Python FastAPI, with HTTPX for GitHub and Gemini REST API requests.
- **Persistence:** SQLAlchemy with SQLite. The default local database is `backend/.data/devpilot.db`.
- **AI:** Google Gemini API, called from the backend over HTTPX; no Gemini SDK is used.

The versions above are read from the current frontend package configuration. Backend dependencies are listed in `backend/requirements.txt`.

## Local Setup and Running

### Prerequisites

- Node.js and npm. The project has been developed with Node.js 22; `frontend/package-lock.json` is provided for reproducible npm installation.
- Python 3 with `venv` support and `pip`.
- A Gemini API key to use Q&A. Repository inspection and source retrieval use GitHub's REST API and do not require a GitHub token for public repositories.

### Configure the backend

From the project root, create a virtual environment and install the listed dependencies:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Set `GEMINI_API_KEY` in the backend process environment or in `backend/.env`. The backend loads that specific file at startup without overriding a value already present in the process environment. Keep credentials on the backend; never put them in a `NEXT_PUBLIC_*` variable or commit them.

Optional backend settings:

| Variable | Purpose |
| --- | --- |
| `GEMINI_MODEL` | Gemini model name. Defaults to `gemini-3.8-flash` in the current backend code. |
| `GITHUB_TOKEN` | Optional backend-only Bearer token for GitHub REST API requests. Public repositories remain the only supported repositories. |
| `DEVPILOT_DATABASE_URL` | Optional SQLite URL. The default is `backend/.data/devpilot.db`; this codebase currently supports SQLite only. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated exact browser origins. Defaults to `http://localhost:3000,http://127.0.0.1:3000`; wildcard origins are rejected. |
| `GEMINI_QA_RATE_LIMIT` | Maximum Q&A requests per client in the configured window; default `10`, accepted range `1`–`60`. |
| `GEMINI_QA_RATE_WINDOW_SECONDS` | Q&A rate-limit window; default `60` seconds, accepted range `1`–`3600`. |

For example, `DEVPILOT_DATABASE_URL` can be set to `sqlite:////absolute/path/to/devpilot.db`. The database URL and credentials, if any, should remain private. `backend/.data/` and environment files are ignored by Git.

### Start the backend

From the project root, in one terminal:

```bash
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

The API docs are at <http://127.0.0.1:8000/docs> and the health check is at <http://127.0.0.1:8000/healthz>.

### Install and start the frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:3000>. The frontend uses `http://localhost:8000` as its backend URL by default. To point it at another backend, set `NEXT_PUBLIC_API_BASE_URL` when starting Next.js, for example:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

### Run checks

Backend tests use Python's `unittest` runner. From the project root:

```bash
cd backend
.venv/bin/python -m unittest discover -s tests
```

Frontend tests use Node's built-in test runner; there is no `npm test` script. From the frontend directory:

```bash
cd frontend
node --experimental-strip-types --test tests/*.test.mjs
npm run lint
npx tsc --noEmit
```

## How to Demonstrate DevPilot

1. Start the backend and frontend, then open the dashboard.
2. Enter a public GitHub repository URL and inspect it.
3. Select a source file in the displayed tree and ask a question in single-file Q&A. To include related code, enable the related-files option; the answer shows the included source paths and any context limitations.
4. In Developer Memory, save a repository decision. The panel labels these decisions as shared and warns against storing secrets or private information.
5. Ask a Q&A question about the recorded decision. DevPilot can summarize it as historical Developer Memory while using source citations for claims about current code behavior.

## Current Limitations

- Only public GitHub repositories are supported. Optional GitHub authentication can improve API quota availability but does not enable private repositories.
- Related-file discovery is heuristic and bounded: it resolves only direct relative JavaScript/TypeScript imports and re-exports, with at most three related files. It does not traverse deeper dependency graphs or resolve TypeScript path aliases.
- Related Q&A allows up to four files total, up to 128 KiB per file, up to 256 KiB of source context, and a 30-second discovery/fetch deadline. An incomplete tree or unresolved/omitted import means the repository was not fully analyzed.
- Citation syntax and line ranges are checked against supplied source text. Citation checks do not establish semantic support for a claim.
- Developer Memory is shared by all DevPilot users of a public repository. There is no user authentication or private decision access control. Do not store secrets, credentials, or private information.
- Q&A includes at most five relevant same-repository decisions, within an 8 KiB memory-context limit. Saved decisions are untrusted historical context and are not treated as proof of current source behavior.
- The local database is SQLite at `backend/.data/devpilot.db` by default. The backend accepts SQLite URLs only; no PostgreSQL adapter or migration framework is configured.
- SQLite data on the local machine persists in that file, but it must not be assumed durable when deployed to a filesystem that may be ephemeral. In particular, the repository does not configure a durable Render volume or managed database; data may be lost after service restart, replacement, or redeployment. Choose and configure durable storage before promising deployed Developer Memory persistence.
- Q&A and Developer Memory write limits are in-memory and process-local. They reset on restart and are not shared across multiple workers or instances, so they are basic demo abuse protection rather than authentication or distributed rate limiting.
- Recent Activity currently shows an empty state; there is no activity-tracking or activity persistence system.
- API Guardian / API Diagnostics is a roadmap placeholder and is not implemented.

## Future Scope

These are planned possibilities, not current capabilities:

- Implement API Guardian diagnostics and relevant test generation.
- Add stronger citation verification that evaluates whether cited code supports each claim.
- Discover deeper dependency relationships while retaining strict context and request limits.
- Select durable deployment storage and add appropriate schema migration support before offering persistent hosted Developer Memory.
- Add authentication and access controls if shared public-repository memory needs user-level permissions.

## Project Status

DevPilot is a hackathon prototype. Public repository inspection, single-file and bounded related-file Q&A, and repository-scoped shared Developer Memory are implemented in the current codebase. Backend and frontend automated tests and static checks are available using the commands above; running those commands verifies the checkout locally. API Guardian and stronger semantic citation verification remain planned work. The current SQLite persistence setup is local-first and is not a deployment durability guarantee.
