export type PromoTerms = {
  kind: "hours" | "subscription_days" | "discount";
  hours: number | null;
  days: number | null;
  discount_percent: number | null;
  discount_kopecks: number | null;
};

export type PromoState = {
  disabled_at: string | null;
  valid_until: string | null;
  max_redemptions: number | null;
  redeemed: number;
};

const rubles = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

export function describeTerms(terms: PromoTerms) {
  if (terms.kind === "hours") return `${terms.hours ?? 0} ч обработки`;
  if (terms.kind === "subscription_days") return `${terms.days ?? 0} дн. подписки`;
  if (terms.discount_percent !== null) return `Скидка ${terms.discount_percent}%`;
  return `Скидка ${rubles.format((terms.discount_kopecks ?? 0) / 100)} ₽`;
}

export function promoStatus(promo: PromoState, now = Date.now()) {
  if (promo.disabled_at) return "Отключён";
  if (promo.valid_until && new Date(promo.valid_until).getTime() <= now) return "Истёк";
  if (promo.max_redemptions !== null && promo.redeemed >= promo.max_redemptions) return "Исчерпан";
  return "Действует";
}

export function usageLabel(promo: PromoState) {
  return promo.max_redemptions === null ? `${promo.redeemed}` : `${promo.redeemed} из ${promo.max_redemptions}`;
}

export function endOfMoscowDay(isoDate: string) {
  return `${isoDate}T23:59:59+03:00`;
}

export const promoCodePattern = /^[A-Za-z0-9_-]{4,32}$/;
