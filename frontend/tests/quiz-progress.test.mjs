import assert from "node:assert/strict";
import { test } from "node:test";
import {
  clearProgress,
  loadProgress,
  parseProgress,
  progressKey,
  quizFingerprint,
  saveProgress,
  serializeProgress,
} from "../src/features/quiz/progress.ts";

const questions = [
  { question: "Q1", options: ["a", "b", "c"], correct_index: 1, explanation: "", timestamp: 10 },
  { question: "Q2", options: ["a", "b"], correct_index: 0, explanation: "", timestamp: 95.5 },
  { question: "Q3", options: ["a", "b", "c", "d"], correct_index: 3, explanation: "", timestamp: 300 },
];

function memoryStorage() {
  const items = new Map();
  return {
    items,
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
  };
}

test("saved progress is restored for the same questions", () => {
  const store = memoryStorage();
  const progress = { answers: [1, 1, null], index: 1 };
  saveProgress("lecture-1", questions, progress, () => store);
  assert.deepEqual(loadProgress("lecture-1", questions, () => store), progress);
  assert.equal(JSON.parse(store.items.get(progressKey("lecture-1"))).score, 1);
});

test("finished quiz is restored on the result screen", () => {
  const store = memoryStorage();
  const progress = { answers: [1, 0, 2], index: 3 };
  saveProgress("lecture-1", questions, progress, () => store);
  assert.deepEqual(loadProgress("lecture-1", questions, () => store), progress);
});

test("progress of another lecture is not used", () => {
  const store = memoryStorage();
  saveProgress("lecture-1", questions, { answers: [1, null, null], index: 1 }, () => store);
  assert.equal(loadProgress("lecture-2", questions, () => store), null);
});

test("changed question set drops saved progress", () => {
  const store = memoryStorage();
  saveProgress("lecture-1", questions, { answers: [1, 0, null], index: 2 }, () => store);
  const regenerated = questions.map((question, at) => (at === 1 ? { ...question, question: "Q2 new" } : question));
  assert.notEqual(quizFingerprint(regenerated), quizFingerprint(questions));
  assert.equal(loadProgress("lecture-1", regenerated, () => store), null);
  assert.equal(store.items.has(progressKey("lecture-1")), false);
});

test("restart clears saved progress", () => {
  const store = memoryStorage();
  saveProgress("lecture-1", questions, { answers: [1, null, null], index: 1 }, () => store);
  clearProgress("lecture-1", () => store);
  assert.equal(loadProgress("lecture-1", questions, () => store), null);
});

test("broken or inconsistent records are rejected", () => {
  const valid = JSON.parse(serializeProgress(questions, { answers: [1, 0, null], index: 2 }));
  assert.equal(parseProgress("{not json", questions), null);
  assert.equal(parseProgress("null", questions), null);
  assert.equal(parseProgress(JSON.stringify({ ...valid, answers: [1, 0] }), questions), null);
  assert.equal(parseProgress(JSON.stringify({ ...valid, answers: [1, 7, null] }), questions), null);
  assert.equal(parseProgress(JSON.stringify({ ...valid, index: 5 }), questions), null);
  assert.equal(parseProgress(JSON.stringify({ ...valid, answers: [1, null, null] }), questions), null);
  assert.equal(parseProgress(JSON.stringify({ ...valid, score: 0 }), questions), null);
  assert.deepEqual(parseProgress(JSON.stringify(valid), questions), { answers: [1, 0, null], index: 2 });
});

test("unavailable storage does not break the quiz", () => {
  const broken = () => {
    throw new Error("SecurityError");
  };
  assert.doesNotThrow(() => saveProgress("lecture-1", questions, { answers: [null, null, null], index: 0 }, broken));
  assert.equal(loadProgress("lecture-1", questions, broken), null);
  assert.doesNotThrow(() => clearProgress("lecture-1", broken));
});
