import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { afterEach, test } from "node:test";
import { createId } from "../src/lib/id.ts";

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");

function replaceCrypto(value) {
  Object.defineProperty(globalThis, "crypto", { value, configurable: true, writable: true });
}

afterEach(() => {
  Object.defineProperty(globalThis, "crypto", original);
});

test("uses randomUUID when the browser has it", () => {
  replaceCrypto({ randomUUID: () => "from-browser" });
  assert.equal(createId(), "from-browser");
});

test("builds a v4 uuid from getRandomValues when randomUUID is missing", () => {
  replaceCrypto({ getRandomValues: (bytes) => webcrypto.getRandomValues(bytes) });
  const ids = new Set(Array.from({ length: 50 }, () => createId()));
  assert.equal(ids.size, 50);
  for (const id of ids) assert.match(id, uuidPattern);
});

test("still returns a v4 uuid without crypto at all", () => {
  replaceCrypto(undefined);
  assert.match(createId(), uuidPattern);
});
