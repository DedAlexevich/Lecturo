import assert from "node:assert/strict";
import { test } from "node:test";
import { labelEvery, lastDays, niceScale, periodLength, periodProblem, readPeriod } from "../src/pages/admin/users/stats.ts";

test("lastDays includes today", () => {
  assert.deepEqual(lastDays(7, new Date(2026, 9, 28)), { from: "2026-10-22", to: "2026-10-28" });
  assert.deepEqual(lastDays(1, new Date(2026, 0, 1)), { from: "2026-01-01", to: "2026-01-01" });
  assert.deepEqual(lastDays(30, new Date(2026, 2, 1)), { from: "2026-01-31", to: "2026-03-01" });
});

test("periodLength counts both ends and rejects broken dates", () => {
  assert.equal(periodLength({ from: "2026-10-01", to: "2026-10-31" }), 31);
  assert.equal(periodLength({ from: "2026-03-28", to: "2026-03-30" }), 3);
  assert.equal(periodLength({ from: "2026-02-30", to: "2026-03-01" }), null);
  assert.equal(periodLength({ from: "", to: "2026-03-01" }), null);
});

test("periodProblem matches the server limits", () => {
  assert.equal(periodProblem({ from: "2026-10-01", to: "2026-10-01" }), null);
  assert.equal(periodProblem({ from: "2026-10-02", to: "2026-10-01" }), "Начало периода позже конца");
  assert.equal(periodProblem({ from: "2025-01-01", to: "2026-01-01" }), null);
  assert.equal(periodProblem({ from: "2025-01-01", to: "2026-01-02" }), "Период не длиннее 366 дней");
  assert.equal(periodProblem({ from: "2026-13-01", to: "2026-10-01" }), "Укажите обе даты");
});

test("readPeriod falls back on missing or invalid params", () => {
  const fallback = { from: "2026-10-01", to: "2026-10-30" };
  assert.deepEqual(readPeriod(new URLSearchParams(""), fallback), fallback);
  assert.deepEqual(readPeriod(new URLSearchParams("from=2026-10-05"), fallback), fallback);
  assert.deepEqual(readPeriod(new URLSearchParams("from=2026-10-09&to=2026-10-05"), fallback), fallback);
  assert.deepEqual(readPeriod(new URLSearchParams("from=2026-09-01&to=2026-09-30"), fallback), {
    from: "2026-09-01",
    to: "2026-09-30",
  });
});

test("niceScale picks round whole steps above the maximum", () => {
  assert.deepEqual(niceScale(0), { top: 4, ticks: [0, 1, 2, 3, 4] });
  assert.deepEqual(niceScale(3), { top: 4, ticks: [0, 1, 2, 3, 4] });
  assert.deepEqual(niceScale(17), { top: 20, ticks: [0, 5, 10, 15, 20] });
  assert.deepEqual(niceScale(90), { top: 100, ticks: [0, 25, 50, 75, 100] });
  const big = niceScale(1_234_567);
  assert.ok(big.top >= 1_234_567);
  assert.ok(big.ticks.every(Number.isInteger));
});

test("labelEvery keeps at most seven day labels", () => {
  assert.equal(labelEvery(7), 1);
  assert.equal(labelEvery(30), 5);
  assert.equal(labelEvery(366), 53);
});
