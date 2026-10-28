import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDuration } from "../src/lib/duration.ts";
import { plural } from "../src/lib/plural.ts";

test("formatDuration shows a short lecture the same way everywhere", () => {
  assert.equal(formatDuration(30), "меньше минуты");
  assert.equal(formatDuration(59), "меньше минуты");
  assert.equal(formatDuration(90), "2 мин");
  assert.equal(formatDuration(450), "8 мин");
});

test("formatDuration switches to hours", () => {
  assert.equal(formatDuration(3600), "1 ч");
  assert.equal(formatDuration(3570), "1 ч");
  assert.equal(formatDuration(4500), "1 ч 15 мин");
  assert.equal(formatDuration(36000), "10 ч");
});

test("formatDuration handles missing and empty time", () => {
  assert.equal(formatDuration(null), "—");
  assert.equal(formatDuration(0), "0 мин");
  assert.equal(formatDuration(-5), "0 мин");
});

test("plural picks the Russian form by the last digits", () => {
  const word = (count) => plural(count, "лекция", "лекции", "лекций");
  assert.equal(word(1), "лекция");
  assert.equal(word(21), "лекция");
  assert.equal(word(101), "лекция");
  assert.equal(word(2), "лекции");
  assert.equal(word(4), "лекции");
  assert.equal(word(34), "лекции");
  assert.equal(word(0), "лекций");
  assert.equal(word(5), "лекций");
  assert.equal(word(11), "лекций");
  assert.equal(word(12), "лекций");
  assert.equal(word(14), "лекций");
  assert.equal(word(111), "лекций");
  assert.equal(word(112), "лекций");
});
