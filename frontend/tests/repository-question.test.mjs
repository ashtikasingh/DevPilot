import assert from "node:assert/strict";
import test from "node:test";

import {
  beginRequest,
  getContextCoverageMessage,
  getQuestionEndpoint,
  getSourceLabel,
  invalidateRequest,
  isCurrentRequest,
} from "../lib/repository-question.ts";

test("single-file mode remains the default endpoint and related mode is opt-in", () => {
  assert.equal(getQuestionEndpoint("single-file"), "/api/repositories/ask");
  assert.equal(getQuestionEndpoint("related-files"), "/api/repositories/ask-related");
});

test("related source metadata keeps stable IDs and repository paths visible", () => {
  assert.equal(
    getSourceLabel({ source_id: "F2", path: "src/lib/client.ts", size_bytes: 128 }),
    "F2 · src/lib/client.ts",
  );
});

test("coverage metadata distinguishes complete from limited context", () => {
  assert.equal(getContextCoverageMessage(true, null), null);
  assert.equal(
    getContextCoverageMessage(false, "GitHub truncated the repository tree"),
    "GitHub truncated the repository tree",
  );
  assert.match(getContextCoverageMessage(false, null) ?? "", /not fully analyzed/);
});

test("a selected-file change invalidates the pending question result", () => {
  const identity = { current: 0 };
  const pendingRequest = beginRequest(identity);

  invalidateRequest(identity);

  assert.equal(isCurrentRequest(identity, pendingRequest), false);
});

test("a related-mode change invalidates the answer from the previous mode", () => {
  const identity = { current: 0 };
  const singleFileRequest = beginRequest(identity);

  invalidateRequest(identity);

  assert.equal(isCurrentRequest(identity, singleFileRequest), false);
});

test("a newer overlapping request is the only request allowed to update state", () => {
  const identity = { current: 0 };
  const olderRequest = beginRequest(identity);
  const newerRequest = beginRequest(identity);

  assert.equal(isCurrentRequest(identity, olderRequest), false);
  assert.equal(isCurrentRequest(identity, newerRequest), true);
});

test("editing the question clears state and ignores a request that completes afterward", async () => {
  const identity = { current: 0 };
  const oldRequest = beginRequest(identity);
  let answer = null;
  let error = null;
  let isAsking = true;
  let completeOldRequest;
  const oldResponse = new Promise((resolve) => {
    completeOldRequest = resolve;
  });
  const applyOldResponse = oldResponse.then((result) => {
    if (isCurrentRequest(identity, oldRequest)) {
      answer = result;
      error = "previous error";
      isAsking = false;
    }
  });

  // Match the question input's invalidation and state reset on edit.
  invalidateRequest(identity);
  answer = null;
  error = null;
  isAsking = false;

  // The old request may still resolve, but its guarded update must be ignored.
  completeOldRequest("answer to the previous question");
  await applyOldResponse;

  assert.equal(answer, null);
  assert.equal(error, null);
  assert.equal(isAsking, false);
});
