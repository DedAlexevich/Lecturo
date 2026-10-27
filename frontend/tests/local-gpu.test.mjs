import assert from "node:assert/strict";
import { test } from "node:test";
import { NO_GPU_MESSAGE, REQUIRED_LIMITS, assessAdapter, friendlyNotesError } from "../src/local/llm/gpu.ts";

const goodLimits = { ...REQUIRED_LIMITS };
const adapter = (overrides = {}) => ({ isFallbackAdapter: false, features: new Set(), limits: goodLimits, ...overrides });

test("accepts a hardware adapter with enough limits", () => {
  assert.deepEqual(assessAdapter(adapter()), { ok: true });
});

test("rejects a missing adapter", () => {
  assert.deepEqual(assessAdapter(null), { ok: false, reason: "no-adapter" });
  assert.deepEqual(assessAdapter(undefined), { ok: false, reason: "no-adapter" });
});

test("rejects a software fallback adapter", () => {
  assert.deepEqual(assessAdapter(adapter({ isFallbackAdapter: true })), { ok: false, reason: "software" });
});

test("rejects adapters with too small buffer limits", () => {
  const small = (name) => adapter({ limits: { ...goodLimits, [name]: goodLimits[name] - 1 } });
  assert.deepEqual(assessAdapter(small("maxBufferSize")), { ok: false, reason: "limits" });
  assert.deepEqual(assessAdapter(small("maxStorageBufferBindingSize")), { ok: false, reason: "limits" });
  assert.deepEqual(assessAdapter(adapter({ limits: {} })), { ok: false, reason: "limits" });
});

test("turns GPU errors from the worker into a clear message", () => {
  assert.equal(friendlyNotesError("Unable to find a compatible GPU. This issue might be because your computer doesn't have a GPU."), NO_GPU_MESSAGE);
  assert.equal(friendlyNotesError("WebGPU is not supported in your current environment"), NO_GPU_MESSAGE);
  assert.equal(friendlyNotesError("Модель вернула пустой ответ"), "Модель вернула пустой ответ");
});
