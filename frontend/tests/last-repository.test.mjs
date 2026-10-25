import assert from "node:assert/strict";
import test from "node:test";

import {
  beginRepositoryRequest,
  clearLastRepository,
  isCurrentRepositoryRequest,
  LAST_REPOSITORY_STORAGE_KEY,
  parseSavedRepository,
  readLastRepository,
  saveLastRepository,
  invalidateRepositoryRequest,
} from "../lib/last-repository.ts";

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem(key) { return data.has(key) ? data.get(key) : null; },
    setItem(key, value) { data.set(key, value); },
    removeItem(key) { data.delete(key); },
  };
}

test("saved identity parser accepts canonical owner/repository only", () => {
  assert.deepEqual(parseSavedRepository(null), { status: "missing" });
  assert.deepEqual(parseSavedRepository('{"full_name":"Example/Project.ts"}'), {
    status: "valid",
    repository: { full_name: "Example/Project.ts" },
  });
});

test("malformed or unexpected storage data is invalid and cleared", () => {
  for (const value of ["not json", "{}", '{"full_name":"../private"}', '{"full_name":"A/B","content":"not stored"}']) {
    assert.equal(parseSavedRepository(value).status, "invalid");
  }

  const storage = memoryStorage({ [LAST_REPOSITORY_STORAGE_KEY]: "not json" });
  assert.deepEqual(readLastRepository(storage), { status: "invalid" });
  assert.equal(storage.data.has(LAST_REPOSITORY_STORAGE_KEY), false);
});

test("save and clear persist only the repository identity", () => {
  const storage = memoryStorage();
  assert.equal(saveLastRepository("Example/Project", storage), true);
  assert.deepEqual([...storage.data.entries()], [
    [LAST_REPOSITORY_STORAGE_KEY, '{"full_name":"Example/Project"}'],
  ]);
  assert.equal(saveLastRepository("not/a/repository/identity", storage), false);
  assert.equal(clearLastRepository(storage), true);
  assert.equal(readLastRepository(storage).status, "missing");
});

test("storage failures are handled without throwing", () => {
  const brokenStorage = {
    getItem() { throw new Error("unavailable"); },
    setItem() { throw new Error("unavailable"); },
    removeItem() { throw new Error("unavailable"); },
  };
  assert.deepEqual(readLastRepository(brokenStorage), { status: "unavailable" });
  assert.equal(saveLastRepository("Example/Project", brokenStorage), false);
  assert.equal(clearLastRepository(brokenStorage), false);
});

test("manual inspection invalidates stale restoration successes and failures", async () => {
  for (const result of ["restored repository", new Error("restore failed")]) {
    const identity = { current: 0 };
    const restoreId = beginRepositoryRequest(identity);
    let displayed = null;
    const restoreResult = result instanceof Error ? Promise.reject(result) : Promise.resolve(result);
    const restore = restoreResult.then((value) => {
      if (isCurrentRepositoryRequest(identity, restoreId)) displayed = value;
    }).catch((error) => {
      if (isCurrentRepositoryRequest(identity, restoreId)) displayed = error.message;
    });

    // A manual switch takes ownership of UI state before restore completes.
    invalidateRepositoryRequest(identity);
    displayed = "manual inspection";
    await restore;

    assert.equal(displayed, "manual inspection");
  }
});

test("a newer restore request is the only current request", () => {
  const identity = { current: 0 };
  const oldRequest = beginRepositoryRequest(identity);
  const currentRequest = beginRepositoryRequest(identity);
  assert.equal(isCurrentRepositoryRequest(identity, oldRequest), false);
  assert.equal(isCurrentRepositoryRequest(identity, currentRequest), true);
});
