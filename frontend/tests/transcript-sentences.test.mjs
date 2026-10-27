import assert from "node:assert/strict";
import { test } from "node:test";
import { findActiveSegment, groupTranscript, joinSentences } from "../src/pages/lecture/time.ts";

function segment(start, end, text) {
  return { start, end, text };
}

function texts(sentences) {
  return sentences.map((sentence) => sentence.text);
}

test("short pieces are joined into one sentence", () => {
  const sentences = joinSentences([segment(1501, 1502, "Это"), segment(1502, 1503.4, "Действительно важная.")]);
  assert.deepEqual(texts(sentences), ["Это Действительно важная."]);
  assert.equal(sentences[0].start, 1501);
  assert.equal(sentences[0].end, 1503.4);
  assert.equal(sentences[0].segments.length, 2);
});

test("sentence ends on terminal punctuation", () => {
  const sentences = joinSentences([
    segment(0, 1, "Первое."),
    segment(1, 2, "Второе!"),
    segment(2, 3, "Третье?"),
    segment(3, 4, "Четвёртое…"),
    segment(4, 5, "Пятое «в кавычках.»"),
    segment(5, 6, "Шестое"),
  ]);
  assert.deepEqual(texts(sentences), [
    "Первое.", "Второе!", "Третье?", "Четвёртое…", "Пятое «в кавычках.»", "Шестое",
  ]);
});

test("long pause splits a sentence", () => {
  const sentences = joinSentences([segment(0, 2, "до паузы"), segment(3.6, 5, "после паузы")]);
  assert.deepEqual(texts(sentences), ["до паузы", "после паузы"]);
});

test("short pause keeps the sentence together", () => {
  const sentences = joinSentences([segment(0, 2, "до паузы"), segment(3.4, 5, "после паузы")]);
  assert.deepEqual(texts(sentences), ["до паузы после паузы"]);
});

test("sentence is not longer than 25 seconds", () => {
  const pieces = Array.from({ length: 12 }, (_, index) => segment(index * 4, index * 4 + 4, `кусок${index}`));
  const sentences = joinSentences(pieces);
  assert.ok(sentences.length > 1);
  for (const sentence of sentences) assert.ok(sentence.end - sentence.start <= 25);
  assert.equal(sentences.flatMap((sentence) => sentence.segments).length, pieces.length);
  assert.deepEqual(sentences.map((sentence) => sentence.start), [0, 24]);
});

test("sentence does not cross a chapter start", () => {
  const sentences = joinSentences(
    [segment(0, 1, "конец"), segment(1, 2, "первой"), segment(2, 3, "начало"), segment(3, 4, "второй.")],
    [{ start: 0 }, { start: 2 }],
  );
  assert.deepEqual(texts(sentences), ["конец первой", "начало второй."]);
});

test("chapter headings stay before their sentences", () => {
  const chapters = [{ start: 0 }, { start: 10 }];
  const sentences = joinSentences(
    [segment(0, 1, "Это"), segment(1, 2, "важно."), segment(10, 11, "Новая"), segment(11, 12, "глава.")],
    chapters,
  );
  const layout = groupTranscript(sentences, chapters).map((row) =>
    row.kind === "chapter" ? `C${row.chapterIndex}` : row.segment.text,
  );
  assert.deepEqual(layout, ["C0", "Это важно.", "C1", "Новая глава."]);
});

test("active sentence is found by player time", () => {
  const sentences = joinSentences([
    segment(0, 1, "Это"), segment(1, 2, "важно."), segment(2, 3, "А"), segment(3, 4, "это нет."),
  ]);
  assert.equal(findActiveSegment(sentences, 1.5), 0);
  assert.equal(findActiveSegment(sentences, 3.5), 1);
});

test("empty input gives no sentences", () => {
  assert.deepEqual(joinSentences([]), []);
});
