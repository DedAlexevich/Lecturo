import assert from "node:assert/strict";
import { test } from "node:test";
import {
  PART_CHARS,
  REDUCE_CHARS,
  buildChapters,
  buildOutline,
  digestRequest,
  formatPart,
  groupDigests,
  parseJson,
  splitIntoParts,
  toDigest,
} from "../src/local/llm/outline.ts";

function lecture(minutes, phrase = "Сегодня разбираем производную сложной функции и правило цепочки.") {
  const segments = [];
  for (let start = 0; start < minutes * 60; start += 4) {
    segments.push({ start, end: start + 4, text: phrase });
  }
  return segments;
}

test("splitIntoParts keeps every part within the character budget", () => {
  const segments = lecture(10);
  const parts = splitIntoParts(segments);
  assert.ok(parts.length >= 2);
  assert.deepEqual(parts.flat(), segments);
  for (const part of parts.slice(0, -1)) assert.ok(formatPart(part).length <= PART_CHARS);
});

test("splitIntoParts merges a short tail into the previous part", () => {
  const segments = [
    { start: 0, end: 1, text: "а".repeat(60) },
    { start: 1, end: 2, text: "б".repeat(60) },
    { start: 2, end: 3, text: "в".repeat(5) },
  ];
  assert.equal(splitIntoParts(segments, 140).length, 1);
});

test("a ten-minute lecture fits into a single reduce request", () => {
  const segments = lecture(10);
  const digests = splitIntoParts(segments).map((part) =>
    toDigest(part, { summary: "Лектор выводит правило цепочки и разбирает три примера с проверкой ответа.".repeat(4), topics: [{ title: "Правило цепочки", start: part[0].start }] }),
  );
  const groups = groupDigests("Матанализ", digests);
  assert.equal(groups.length, 1);
  assert.ok(digestRequest("Матанализ", groups[0]).length <= REDUCE_CHARS);
});

test("groupDigests splits long lectures into several requests", () => {
  const digests = splitIntoParts(lecture(90)).map((part) => toDigest(part, { summary: "x".repeat(800), topics: [] }));
  const groups = groupDigests("Лекция", digests);
  assert.ok(groups.length > 1);
  assert.deepEqual(groups.flat(), digests);
  for (const group of groups.filter((item) => item.length > 1)) assert.ok(digestRequest("Лекция", group).length <= REDUCE_CHARS);
});

test("parseJson extracts the object and rejects broken output", () => {
  assert.deepEqual(parseJson('ответ: {"summary": "ок", "topics": []} конец'), { summary: "ок", topics: [] });
  assert.equal(parseJson('{"summary": "обрыв'), null);
  assert.equal(parseJson("[1, 2]"), null);
});

test("toDigest drops topics without title or timecode", () => {
  const part = [{ start: 10, end: 20, text: "текст" }];
  const digest = toDigest(part, { summary: " Итог ", topics: [{ title: "Тема", start: "12" }, { title: "", start: 3 }, { title: "Без времени" }] });
  assert.deepEqual(digest, { start: 10, end: 20, summary: "Итог", topics: [{ title: "Тема", start: 12 }] });
});

test("buildChapters snaps to segments, orders and closes ranges", () => {
  const segments = [
    { start: 0, end: 30, text: "а" },
    { start: 30, end: 61, text: "б" },
    { start: 61, end: 120, text: "в" },
  ];
  const chapters = buildChapters(
    [
      { title: "Вторая", start: 59, summary: "Про б" },
      { title: "Первая", start: 4, summary: "Про а" },
      { title: "Повтор", start: 62, summary: "" },
      { title: "", start: 90 },
    ],
    segments,
    [],
  );
  assert.deepEqual(chapters, [
    { title: "Первая", start: 0, end: 61, summary: "Про а" },
    { title: "Вторая", start: 61, end: 120, summary: "Про б" },
  ]);
});

test("buildOutline falls back to parts when the model gave nothing", () => {
  const segments = [
    { start: 5, end: 60, text: "а" },
    { start: 60, end: 120, text: "б" },
  ];
  const digests = [
    { start: 5, end: 60, summary: "Начало", topics: [{ title: "Введение", start: 5 }] },
    { start: 60, end: 120, summary: "Продолжение", topics: [] },
  ];
  const outline = buildOutline([null], segments, digests);
  assert.deepEqual(outline.chapters, [
    { title: "Введение", start: 5, end: 60, summary: "Начало" },
    { title: "Часть 2", start: 60, end: 120, summary: "Продолжение" },
  ]);
  assert.equal(outline.summaryMd, "## Введение\n\nНачало\n\n## Часть 2\n\nПродолжение");
});

test("buildOutline joins chapters and summaries of every request", () => {
  const segments = [
    { start: 0, end: 50, text: "а" },
    { start: 50, end: 100, text: "б" },
  ];
  const outline = buildOutline(
    [
      { chapters: [{ title: "Один", start: 0, summary: "" }], summary_md: "## Один\n- пункт" },
      { chapters: [{ title: "Два", start: 50, summary: "" }], summary_md: " ## Два\n- пункт " },
    ],
    segments,
    [],
  );
  assert.deepEqual(outline.chapters.map((chapter) => [chapter.title, chapter.start, chapter.end]), [["Один", 0, 50], ["Два", 50, 100]]);
  assert.equal(outline.summaryMd, "## Один\n- пункт\n\n## Два\n- пункт");
});
