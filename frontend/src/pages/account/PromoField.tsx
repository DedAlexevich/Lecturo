import { useId, useState } from "react";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Input";
import styles from "./AccountPage.module.css";
import { errorMessage, useApplyPromo, type Promo } from "./billing";
import { discountLabel, normalizePromoCode } from "./promo";

type PromoFieldProps = {
  discount: Promo | null;
  onDiscount: (promo: Promo | null) => void;
};

export function PromoField({ discount, onDiscount }: PromoFieldProps) {
  const inputId = useId();
  const resultId = useId();
  const [draft, setDraft] = useState("");
  const [applied, setApplied] = useState<string | null>(null);
  const applyPromo = useApplyPromo();
  const code = normalizePromoCode(draft);

  const apply = () => {
    if (!code) return;
    setApplied(null);
    applyPromo.mutate(code, {
      onSuccess: (promo) => {
        setDraft("");
        if (promo.applied) setApplied(promo.message);
        else onDiscount(promo);
      },
    });
  };

  if (discount) {
    return (
      <div className={styles.promoApplied} role="status">
        <span>
          Промокод {discount.code}: скидка {discountLabel(discount)} при оплате
        </span>
        <Button size="sm" variant="ghost" onClick={() => onDiscount(null)}>
          Убрать
        </Button>
      </div>
    );
  }

  return (
    <div className={styles.promo}>
      <label className={styles.promoLabel} htmlFor={inputId}>
        Промокод
      </label>
      <div className={styles.promoRow}>
        <Input
          id={inputId}
          value={draft}
          maxLength={64}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          aria-describedby={applyPromo.isError || applied ? resultId : undefined}
          aria-invalid={applyPromo.isError || undefined}
          onChange={(event) => {
            setDraft(event.target.value);
            applyPromo.reset();
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            apply();
          }}
        />
        <Button variant="secondary" disabled={!code} loading={applyPromo.isPending} onClick={apply}>
          Применить
        </Button>
      </div>
      {applyPromo.isError && (
        <p id={resultId} className={styles.alert} role="alert">
          {errorMessage(applyPromo.error, "Не удалось проверить промокод. Попробуйте ещё раз.")}
        </p>
      )}
      {applied && (
        <p id={resultId} className={styles.promoSuccess} role="status">
          {applied}
        </p>
      )}
    </div>
  );
}
