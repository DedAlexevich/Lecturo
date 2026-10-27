import assert from "node:assert/strict";
import { test } from "node:test";
import { etaText, formatDuration, headline, isIndeterminate, stepHint, stepLabel, stepProgress } from "../src/pages/lecture/processingView.ts";

const running = (overrides) => ({ step: "transcribe", status: "running", progress: 0.3, error: null, stage: "recognize", expected_sec: 450, ...overrides });

test("formatDuration rounds to minutes and hours", () => {
  assert.equal(formatDuration(20), "меньше минуты");
  assert.equal(formatDuration(450), "8 мин");
  assert.equal(formatDuration(3600), "1 ч");
  assert.equal(formatDuration(4500), "1 ч 15 мин");
});

test("etaText is hidden without an estimate", () => {
  assert.equal(etaText(null), null);
  assert.equal(etaText(0), null);
  assert.equal(etaText(600), "Осталось примерно 10 мин");
});

test("recognition shows stage labels and hint", () => {
  assert.equal(stepLabel(running({ stage: "upload" })), "Загрузка аудио в хранилище");
  assert.equal(stepLabel(running()), "Распознавание идёт");
  assert.equal(stepLabel(running({ stage: "fetch" })), "Получение результата");
  assert.equal(stepHint(running()), "Распознавание обычно занимает около 8 мин");
});

test("recognition is indeterminate at the limit, without estimate and while uploading", () => {
  assert.equal(isIndeterminate(running()), false);
  assert.equal(stepProgress(running()), 30);
  assert.equal(isIndeterminate(running({ progress: 0.95 })), true);
  assert.equal(stepProgress(running({ progress: 0.95 })), undefined);
  assert.match(stepHint(running({ progress: 0.95 })), /^Ещё немного/);
  assert.equal(isIndeterminate(running({ expected_sec: null })), true);
  assert.equal(isIndeterminate(running({ stage: "upload", progress: 0 })), true);
  assert.equal(isIndeterminate(running({ stage: null, progress: 0 })), true);
});

test("other steps keep plain progress", () => {
  const audio = { step: "audio", status: "running", progress: 0.5, error: null, stage: null, expected_sec: 15 };
  assert.equal(stepProgress(audio), 50);
  assert.equal(stepHint(audio), null);
});

test("headline explains the queue", () => {
  assert.equal(headline("queued", 2), "В очереди, перед вами 2");
  assert.equal(headline("queued", 0), "Файл принят, готовим к обработке");
  assert.equal(headline("processing", null), "Лекция обрабатывается");
});
