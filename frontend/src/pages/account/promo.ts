export const minPaymentKopecks = 100;

export type DiscountTerms = {
  discount_percent: number | null;
  discount_kopecks: number | null;
};

export function discountKopecks(priceRub: number, terms: DiscountTerms) {
  const price = priceRub * 100;
  const raw =
    terms.discount_percent !== null
      ? Math.floor((price * terms.discount_percent) / 100)
      : (terms.discount_kopecks ?? 0);
  return Math.max(0, Math.min(raw, price - minPaymentKopecks));
}

export function discountLabel(terms: DiscountTerms) {
  if (terms.discount_percent !== null) return `${terms.discount_percent}%`;
  const rubles = (terms.discount_kopecks ?? 0) / 100;
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(rubles)} ₽`;
}

export function normalizePromoCode(value: string) {
  return value.trim().toUpperCase();
}
