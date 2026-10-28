import assert from "node:assert/strict";
import { test } from "node:test";
import { describeTerms, endOfMoscowDay, promoStatus, usageLabel } from "../src/pages/admin/promo/terms.ts";
import { discountKopecks, discountLabel, normalizePromoCode } from "../src/pages/account/promo.ts";

const percent = (value) => ({ discount_percent: value, discount_kopecks: null });
const fixed = (value) => ({ discount_percent: null, discount_kopecks: value });

test("discountKopecks matches the server rounding and keeps one ruble", () => {
  assert.equal(discountKopecks(349, percent(25)), 8725);
  assert.equal(discountKopecks(299, percent(33)), 9867);
  assert.equal(discountKopecks(199, fixed(5000)), 5000);
  assert.equal(discountKopecks(199, fixed(1_000_000)), 19800);
  assert.equal(discountKopecks(1, percent(50)), 0);
});

test("discountLabel and normalizePromoCode", () => {
  assert.equal(discountLabel(percent(20)), "20%");
  assert.equal(discountLabel(fixed(15050)), "150,5 ₽");
  assert.equal(normalizePromoCode("  spring-2026 "), "SPRING-2026");
});

const base = { kind: "hours", hours: null, days: null, discount_percent: null, discount_kopecks: null };

test("describeTerms names what the code gives", () => {
  assert.equal(describeTerms({ ...base, hours: 5 }), "5 ч обработки");
  assert.equal(describeTerms({ ...base, kind: "subscription_days", days: 30 }), "30 дн. подписки");
  assert.equal(describeTerms({ ...base, kind: "discount", discount_percent: 15 }), "Скидка 15%");
  assert.equal(describeTerms({ ...base, kind: "discount", discount_kopecks: 10000 }), "Скидка 100 ₽");
});

test("promoStatus checks disabling, expiry and usage in that order", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");
  const active = { disabled_at: null, valid_until: null, max_redemptions: null, redeemed: 3 };
  assert.equal(promoStatus(active, now), "Действует");
  assert.equal(promoStatus({ ...active, disabled_at: "2026-10-01T00:00:00Z" }, now), "Отключён");
  assert.equal(promoStatus({ ...active, valid_until: "2026-10-28T11:59:00Z" }, now), "Истёк");
  assert.equal(promoStatus({ ...active, max_redemptions: 3 }, now), "Исчерпан");
  assert.equal(usageLabel(active), "3");
  assert.equal(usageLabel({ ...active, max_redemptions: 10 }), "3 из 10");
});

test("endOfMoscowDay includes the whole chosen day", () => {
  assert.equal(new Date(endOfMoscowDay("2026-12-31")).toISOString(), "2026-12-31T20:59:59.000Z");
});
