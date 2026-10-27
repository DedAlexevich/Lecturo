import assert from "node:assert/strict";
import { test } from "node:test";
import { placeMenu } from "../src/features/lecture-actions/placement.ts";

test("menu aligns to the right edge of the trigger when it fits on the left", () => {
  assert.deepEqual(placeMenu({ left: 1200, right: 1244 }, 260, 1280), { left: -216 });
});

test("menu aligns to the left edge of the trigger near the left side of the screen", () => {
  assert.deepEqual(placeMenu({ left: 16, right: 60 }, 260, 360), { left: 0 });
});

test("menu spans the screen when it fits on neither side", () => {
  assert.deepEqual(placeMenu({ left: 150, right: 194 }, 300, 320), { left: -142, width: 304 });
});
