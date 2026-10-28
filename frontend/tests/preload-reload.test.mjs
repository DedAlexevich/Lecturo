import assert from "node:assert/strict";
import { test } from "node:test";
import { shouldReloadAfterPreloadError } from "../src/app/preloadReload.ts";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("first missing chunk reloads the page", () => {
  assert.equal(shouldReloadAfterPreloadError(memoryStorage(), 1_000_000), true);
});

test("a second failure right after the reload does not reload again", () => {
  const storage = memoryStorage();
  assert.equal(shouldReloadAfterPreloadError(storage, 1_000_000), true);
  assert.equal(shouldReloadAfterPreloadError(storage, 1_005_000), false);
  assert.equal(shouldReloadAfterPreloadError(storage, 1_050_000), false);
});

test("a later deploy in the same tab can reload once more", () => {
  const storage = memoryStorage();
  shouldReloadAfterPreloadError(storage, 1_000_000);
  assert.equal(shouldReloadAfterPreloadError(storage, 1_000_000 + 10 * 60 * 1000), true);
});

test("without session storage the page is not reloaded", () => {
  const broken = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(shouldReloadAfterPreloadError(broken, 1_000_000), false);
});
