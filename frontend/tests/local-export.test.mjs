import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildCues,
  buildExport,
  exportFileName,
  formatClock,
  toMarkdown,
  toSrt,
  toVtt,
  wrapText,
} from "../src/local/export/format.ts";

const lecture = {
  id: "1",
  title: "Лекция 1: Введение / Основы?",
  createdAt: 0,
  durationSec: 3725,
  language: "ru",
  model: "tiny",
  segments: [
    { start: 0, end: 2.5, text: "Добрый день." },
    { start: 3599.9996, end: 3725, text: "  Это   <b>конец</b> & итог  " },
  ],
  chapters: [{ start: 0, end: 3600, title: "Начало", summary: "Вводная часть" }],
  summaryMd: null,
};

test("formatClock rounds milliseconds without overflowing the seconds field", () => {
  assert.equal(formatClock(0, ","), "00:00:00,000");
  assert.equal(formatClock(3599.9996, ","), "01:00:00,000");
  assert.equal(formatClock(3661.0425, "."), "01:01:01.043");
  assert.equal(formatClock(-3, ","), "00:00:00,000");
});

test("wrapText breaks on words and keeps long words whole", () => {
  assert.deepEqual(wrapText("один два три", 7), ["один", "два три"]);
  assert.deepEqual(wrapText("суперслововчемдлинном и", 5), ["суперслововчемдлинном", "и"]);
  assert.deepEqual(wrapText("   "), []);
});

test("long segments are split into cues of two lines with proportional timing", () => {
  const text = Array.from({ length: 40 }, (_, index) => `слово${index}`).join(" ");
  const cues = buildCues([{ start: 10, end: 30, text }]);
  assert.ok(cues.length > 1);
  assert.equal(cues[0].start, 10);
  assert.equal(cues.at(-1).end, 30);
  for (let index = 1; index < cues.length; index += 1) assert.equal(cues[index].start, cues[index - 1].end);
  for (const cue of cues) {
    assert.ok(cue.lines.length <= 2);
    assert.ok(cue.lines.every((line) => line.length <= 42));
  }
});

test("srt has numbered cues with comma timecodes", () => {
  assert.equal(
    toSrt(lecture),
    "1\n00:00:00,000 --> 00:00:02,500\nДобрый день.\n\n2\n01:00:00,000 --> 01:02:05,000\nЭто <b>конец</b> & итог\n",
  );
});

test("vtt has header, dot timecodes and escaped markup", () => {
  assert.equal(
    toVtt(lecture),
    "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nДобрый день.\n\n01:00:00.000 --> 01:02:05.000\nЭто &lt;b&gt;конец&lt;/b&gt; &amp; итог\n",
  );
  assert.equal(toVtt({ segments: [] }), "WEBVTT\n");
});

test("empty and inverted segments do not break the output", () => {
  const srt = toSrt({ segments: [{ start: 5, end: 1, text: "обратный" }, { start: 6, end: 7, text: "   " }] });
  assert.equal(srt, "1\n00:00:05,000 --> 00:00:05,001\nобратный\n");
});

test("markdown contains title, chapters and timestamped transcript", () => {
  const markdown = toMarkdown(lecture);
  assert.ok(markdown.startsWith("# Лекция 1: Введение / Основы?\n\nДлительность: 1:02:05\n"));
  assert.ok(markdown.includes("## Главы\n\n- **00:00** Начало. Вводная часть"));
  assert.ok(markdown.includes("## Расшифровка\n\n**00:00** Добрый день.\n\n**59:59** Это <b>конец</b> & итог\n"));
  assert.ok(markdown.endsWith("\n"));
});

test("markdown includes summary when present", () => {
  assert.ok(toMarkdown({ ...lecture, summaryMd: "Кратко." }).includes("## Конспект\n\nКратко."));
});

test("file name is built from the title without forbidden characters", () => {
  assert.equal(exportFileName(lecture.title, "srt"), "Лекция 1 Введение Основы.srt");
  assert.equal(exportFileName("  ..  ", "md"), "lecture.md");
  assert.equal(exportFileName("a".repeat(200), "vtt").length, 84);
});

test("buildExport returns name, mime and content", () => {
  const file = buildExport(lecture, "vtt");
  assert.equal(file.name, "Лекция 1 Введение Основы.vtt");
  assert.ok(file.mime.startsWith("text/vtt"));
  assert.ok(file.content.startsWith("WEBVTT"));
});
