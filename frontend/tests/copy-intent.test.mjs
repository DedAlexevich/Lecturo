import assert from "node:assert/strict";
import { test } from "node:test";
import { rememberIntent, takeIntent } from "../src/pages/public/copyIntent.ts";

function memoryStore() {
  const data = new Map();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
  };
}

test("намерение выполняется один раз", () => {
  const store = memoryStore();
  rememberIntent({ token: "abc", lectureId: "l1" }, store);
  assert.equal(takeIntent({ token: "abc", lectureId: "l1" }, store), true);
  assert.equal(takeIntent({ token: "abc", lectureId: "l1" }, store), false);
});

test("намерение для другой ссылки или лекции не срабатывает и не стирается", () => {
  const store = memoryStore();
  rememberIntent({ token: "abc", lectureId: null }, store);
  assert.equal(takeIntent({ token: "xyz", lectureId: null }, store), false);
  assert.equal(takeIntent({ token: "abc", lectureId: "l1" }, store), false);
  assert.equal(takeIntent({ token: "abc", lectureId: null }, store), true);
});

test("без хранилища и с битыми данными намерения нет", () => {
  assert.equal(takeIntent({ token: "abc", lectureId: null }, null), false);
  const store = memoryStore();
  store.setItem("lecturo:save-copy", "{не json");
  assert.equal(takeIntent({ token: "abc", lectureId: null }, store), false);
});
