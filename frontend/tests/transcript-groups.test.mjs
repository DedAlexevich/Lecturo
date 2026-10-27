import assert from "node:assert/strict";
import { test } from "node:test";
import { groupTranscript } from "../src/pages/lecture/time.ts";

const segments = [0, 20, 40, 65, 130, 200].map((start) => ({ start, text: `s${start}` }));

function layout(rows) {
  return rows.map((row) => (row.kind === "chapter" ? `C${row.chapterIndex}` : row.segment.text));
}

test("chapter heading is placed before the first segment of the chapter", () => {
  const chapters = [{ start: 0 }, { start: 60 }, { start: 180 }];
  assert.deepEqual(layout(groupTranscript(segments, chapters)), [
    "C0", "s0", "s20", "s40", "C1", "s65", "s130", "C2", "s200",
  ]);
});

test("segments before the first chapter have no heading", () => {
  const chapters = [{ start: 30 }];
  assert.deepEqual(layout(groupTranscript(segments, chapters)), [
    "s0", "s20", "C0", "s40", "s65", "s130", "s200",
  ]);
});

test("chapter without segments is skipped", () => {
  const chapters = [{ start: 0 }, { start: 90 }, { start: 100 }];
  assert.deepEqual(layout(groupTranscript(segments, chapters)), [
    "C0", "s0", "s20", "s40", "s65", "C2", "s130", "s200",
  ]);
});

test("without chapters rows are plain segments", () => {
  const rows = groupTranscript(segments, []);
  assert.equal(rows.length, segments.length);
  assert.ok(rows.every((row) => row.kind === "segment"));
});

test("segment index points to the original array", () => {
  const rows = groupTranscript(segments, [{ start: 0 }]);
  const indexes = rows.filter((row) => row.kind === "segment").map((row) => row.segmentIndex);
  assert.deepEqual(indexes, [0, 1, 2, 3, 4, 5]);
});
