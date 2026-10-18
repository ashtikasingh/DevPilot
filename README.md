# DevPilot

DevPilot is an AI-assisted developer workspace for inspecting public GitHub
repositories and asking questions about selected source files. It retrieves
repository metadata and file contents through the GitHub REST API; it does not
clone repositories or execute repository code. Codebase Q&A sends the selected
file and question to Gemini from the backend.

## Requirements

- Node.js 22.14 or newer and npm
- Python 3.11 or newer
- A Gemini API key for Codebase Q&A (repository inspection and file viewing use
  the public GitHub API without GitHub authentication)

## Local setup

### Backend

From the project root, create the virtual environment and install the backend
requirements:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Set `GEMINI_API_KEY` in the process environment or in `backend/.env`. The local
`.env` file is ignored by Git. The backend loads that file without overriding a
key already present in the process environment. `GEMINI_MODEL` is optional; the
backend uses its configured default when it is unset.

Start the API from the project root:

```bash
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

The API documentation is available at <http://127.0.0.1:8000/docs>.

### Frontend

In another terminal, install the npm dependencies and start Next.js:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:3000>. The frontend defaults to the backend at
`http://localhost:8000`. To use another backend URL, set
`NEXT_PUBLIC_API_BASE_URL` before starting the frontend, for example:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

## Checks

Run the backend unit tests from the project root:

```bash
cd backend
.venv/bin/python -m unittest discover -s tests
```

Run the frontend lint, TypeScript, and Markdown parser tests:

```bash
cd frontend
npm run lint
npx tsc --noEmit
node --experimental-strip-types --test tests/markdown.test.mjs
```
