import assert from "node:assert/strict";
import { test } from "node:test";
import { splitTranscript } from "../src/local/llm/chunks.ts";
import { notesPrompts } from "../src/local/llm/prompt.ts";

test("splits a ten-minute transcript without losing text or time boundaries", () => {
  const segments = Array.from({ length: 120 }, (_, index) => ({
    start: index * 5,
    end: (index + 1) * 5,
    text: `Фрагмент ${index} рассказывает о важных понятиях этой лекции.`,
  }));
  const chunks = splitTranscript(segments, 300);
  assert.ok(chunks.length > 1);
  assert.equal(chunks.map((chunk) => chunk.text).join(" "), segments.map((segment) => segment.text).join(" "));
  assert.equal(chunks[0].start, 0);
  assert.equal(chunks.at(-1).end, 600);
  assert.ok(chunks.every((chunk) => chunk.text.length <= 300 && chunk.start <= chunk.end));
});

test("handles empty text and oversized words", () => {
  assert.deepEqual(splitTranscript([{ start: 0, end: 1, text: "  " }]), []);
  const chunks = splitTranscript([{ start: 1, end: 2, text: "abcdefghijk" }], 5);
  assert.deepEqual(chunks.map((chunk) => chunk.text), ["abcde", "fghij", "k"]);
  assert.equal(chunks[0].start, 1);
  assert.equal(chunks.at(-1).end, 2);
  assert.ok(chunks.every((chunk, index) => index === 0 || chunks[index - 1].end <= chunk.start));
});

test("chooses a notes prompt that matches the lecture language", () => {
  const russian = notesPrompts("ru");
  const english = notesPrompts("en");
  assert.match(russian.system, /только на русском/);
  assert.match(russian.user, /Назови тему/);
  assert.match(english.system, /only in English/);
  assert.match(english.user, /Give this excerpt/);
});
