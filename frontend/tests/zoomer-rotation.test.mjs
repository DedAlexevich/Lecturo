import assert from "node:assert/strict";
import { test } from "node:test";
import { nextClipIndex, parseStoredIndex, parseStoredMode } from "../src/features/zoomer/rotation.ts";

test("no clip is picked when the folder is empty", () => {
  assert.equal(nextClipIndex(null, 0), null);
  assert.equal(nextClipIndex(2, 0), null);
});

test("first pick starts from the first clip", () => {
  assert.equal(nextClipIndex(null, 3), 0);
});

test("clips go round in order and wrap to the start", () => {
  assert.equal(nextClipIndex(0, 3), 1);
  assert.equal(nextClipIndex(1, 3), 2);
  assert.equal(nextClipIndex(2, 3), 0);
});

test("a stale index after clips were removed still lands inside the list", () => {
  assert.equal(nextClipIndex(7, 2), 0);
  assert.equal(nextClipIndex(4, 2), 1);
});

test("stored index accepts only whole non-negative numbers", () => {
  assert.equal(parseStoredIndex(null), null);
  assert.equal(parseStoredIndex("2"), 2);
  assert.equal(parseStoredIndex("-1"), null);
  assert.equal(parseStoredIndex("1.5"), null);
  assert.equal(parseStoredIndex("abc"), null);
});

test("mode is off unless explicitly stored as on", () => {
  assert.equal(parseStoredMode(null), false);
  assert.equal(parseStoredMode("off"), false);
  assert.equal(parseStoredMode("true"), false);
  assert.equal(parseStoredMode("on"), true);
});
