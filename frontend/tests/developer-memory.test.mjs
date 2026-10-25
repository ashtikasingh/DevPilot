import assert from "node:assert/strict";
import test from "node:test";

import {
  createDecision,
  deleteDecision,
  DeveloperMemoryApiError,
  listDecisions,
  updateDecision,
} from "../lib/developer-memory.ts";

const decision = {
  id: "3d936332-cc14-4963-8b1d-81cf0d646af3",
  repository: "Example/Project",
  title: "Use a stable cursor",
  content: "Keep pagination deterministic.",
  source_path: "src/api.ts",
  created_at: "2026-10-24T10:00:00Z",
  updated_at: "2026-10-24T10:00:00Z",
};

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("list requests use configured API base URL and canonical repository path", async () => {
  let called;
  const result = await listDecisions("Example", "Project", {
    baseUrl: "https://api.example.test/",
    fetcher: async (url, init) => {
      called = { url, init };
      return jsonResponse({ repository: "Example/Project", decisions: [decision], limit: 50, offset: 0 });
    },
  });

  assert.equal(called.url, "https://api.example.test/api/repositories/Example/Project/decisions");
  assert.equal(called.init.method, "GET");
  assert.equal(called.init.cache, "no-store");
  assert.equal(result.decisions[0].id, decision.id);
});

test("create sends the required fields and optional source path as JSON", async () => {
  let called;
  const result = await createDecision("Example", "Project", {
    title: "Use a stable cursor",
    content: "Keep pagination deterministic.",
    source_path: "src/api.ts",
  }, {
    baseUrl: "http://localhost:8000",
    fetcher: async (url, init) => {
      called = { url, init };
      return jsonResponse(decision, 201);
    },
  });

  assert.equal(called.url, "http://localhost:8000/api/repositories/Example/Project/decisions");
  assert.equal(called.init.method, "POST");
  assert.equal(called.init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(called.init.body), {
    title: "Use a stable cursor",
    content: "Keep pagination deterministic.",
    source_path: "src/api.ts",
  });
  assert.equal(result.title, decision.title);
});

test("update uses PATCH with an encoded decision ID and partial payload", async () => {
  let called;
  await updateDecision("Example", "Project", "decision/id", { content: "Updated" }, {
    baseUrl: "https://api.example.test",
    fetcher: async (url, init) => {
      called = { url, init };
      return jsonResponse({ ...decision, content: "Updated" });
    },
  });

  assert.equal(called.url, "https://api.example.test/api/repositories/Example/Project/decisions/decision%2Fid");
  assert.equal(called.init.method, "PATCH");
  assert.deepEqual(JSON.parse(called.init.body), { content: "Updated" });
});

test("delete handles the API's empty 204 response", async () => {
  let called;
  await assert.doesNotReject(deleteDecision("Example", "Project", decision.id, {
    baseUrl: "http://localhost:8000",
    fetcher: async (url, init) => {
      called = { url, init };
      return new Response(null, { status: 204 });
    },
  }));
  assert.equal(called.init.method, "DELETE");
  assert.equal(called.url.endsWith(`/decisions/${decision.id}`), true);
});

test("API errors return the safe server message and sanitized metadata", async () => {
  await assert.rejects(
    listDecisions("Example", "Project", {
      fetcher: async () => jsonResponse({
        error: { code: "decision_write_rate_limited", message: "Wait briefly.", retry_after_seconds: 12 },
      }, 429),
    }),
    (error) => {
      assert.ok(error instanceof DeveloperMemoryApiError);
      assert.equal(error.message, "Wait briefly.");
      assert.equal(error.status, 429);
      assert.equal(error.code, "decision_write_rate_limited");
      assert.equal(error.retryAfterSeconds, 12);
      return true;
    },
  );
});

test("malformed error bodies and network failures never expose raw details", async () => {
  await assert.rejects(
    listDecisions("Example", "Project", {
      fetcher: async () => new Response("private SQL detail", { status: 503 }),
    }),
    (error) => {
      assert.equal(error.message, "Developer Memory request failed. Try again shortly.");
      assert.equal(error.message.includes("private SQL detail"), false);
      return true;
    },
  );

  await assert.rejects(
    listDecisions("Example", "Project", {
      fetcher: async () => { throw new Error("secret connection string"); },
    }),
    (error) => {
      assert.equal(error.message, "Could not reach DevPilot’s API. Check that the backend is running and try again.");
      assert.equal(error.message.includes("secret connection string"), false);
      return true;
    },
  );
});
