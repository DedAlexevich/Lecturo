import assert from "node:assert/strict";
import { test } from "node:test";
import { exportFileName } from "../src/pages/lecture/exportFileName.ts";

test("filename* has priority over filename", () => {
  const header = `attachment; filename="lecture.pdf"; filename*=UTF-8''%D0%9B%D0%B5%D0%BA%D1%86%D0%B8%D1%8F%201.pdf`;
  assert.equal(exportFileName("Заголовок", "pdf", header), "Лекция 1.pdf");
});

test("plain filename is used without filename*", () => {
  assert.equal(exportFileName("Заголовок", "srt", 'attachment; filename="notes.srt"'), "notes.srt");
});

test("broken percent-encoding falls back to filename", () => {
  const header = `attachment; filename="lecture.vtt"; filename*=UTF-8''%E0%A4%A`;
  assert.equal(exportFileName("Заголовок", "vtt", header), "lecture.vtt");
});

test("broken percent-encoding without filename falls back to title", () => {
  assert.equal(exportFileName("Лекция", "pdf", "attachment; filename*=UTF-8''%E0%A4%A"), "Лекция.pdf");
});

test("invalid characters are removed", () => {
  const header = `attachment; filename*=UTF-8''%D0%90%2F%D0%91%3A%3F.pdf`;
  assert.equal(exportFileName("x", "pdf", header), "А Б .pdf");
});

test("missing header uses sanitized title", () => {
  assert.equal(exportFileName("Лекция 1: Введение / Основы?", "pdf", null), "Лекция 1 Введение Основы.pdf");
  assert.equal(exportFileName("???", "vtt", null), "lecture.vtt");
});
