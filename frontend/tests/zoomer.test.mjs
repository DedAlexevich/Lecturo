import assert from "node:assert/strict";
import { test } from "node:test";
import { parseClipList } from "../src/features/zoomer/listing.ts";
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

test("clip list keeps the server order and only clip urls", () => {
  const first = "/zoomer/0b6f2c1e-6a3d-4f8e-9c1a-2d4e5f607182.mp4";
  const second = "/zoomer/9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d.mp4";
  const body = [
    { id: "b", url: second, title: "Второй" },
    { id: "x", url: "https://example.org/clip.mp4" },
    { id: "y", url: "/zoomer/../secret.mp4" },
    { id: "a", url: first, title: "Первый" },
  ];
  assert.deepEqual(parseClipList(body), [second, first]);
});

test("response that is not a clip list gives no clips", () => {
  assert.deepEqual(parseClipList(null), []);
  assert.deepEqual(parseClipList({ url: "/zoomer/a.mp4" }), []);
  assert.deepEqual(parseClipList([null, 3, { url: 5 }]), []);
});
