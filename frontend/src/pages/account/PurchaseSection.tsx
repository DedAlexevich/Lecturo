import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "../../ui/Button";
import { Checkbox } from "../../ui/Checkbox";
import styles from "./AccountPage.module.css";
import { errorMessage, useCreatePayment, useProducts, type Product } from "./billing";
import { formatRubles } from "./format";
import { SectionError, SectionLoading } from "./SectionState";

export function PurchaseSection() {
  const titleId = useId();
  const { data: products, isPending, isError, refetch } = useProducts();

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <div className={styles.sectionHead}>
        <h2 id={titleId} className={styles.sectionTitle}>
          Подписка и пакеты часов
        </h2>
        <p className={styles.muted}>Оплата картой через ЮKassa. После оплаты вы вернётесь в кабинет.</p>
      </div>
      {isPending && <SectionLoading label="Загружаем тарифы" />}
      {isError && <SectionError message="Не удалось загрузить тарифы." onRetry={() => refetch()} />}
      {products && products.length === 0 && <p className={styles.muted}>Сейчас купить ничего нельзя.</p>}
      {products && products.length > 0 && <PurchaseForm products={products} />}
    </section>
  );
}

function productNote(product: Product) {
  if (product.kind === "subscription") return "Больше часов в неделю, квиз, памятка к экзамену и долгое хранение видео";
  if (!product.seconds) return "Не сгорает";
  const perHour = Math.round((product.price_rub / (product.seconds / 3600)) * 100) / 100;
  return `Не сгорает, ${formatRubles(perHour)} за час`;
}

function PurchaseForm({ products }: { products: Product[] }) {
  const [code, setCode] = useState(products[0].code);
  const [accepted, setAccepted] = useState(false);
  const [showConsentError, setShowConsentError] = useState(false);
  const idempotenceKey = useRef(crypto.randomUUID());
  const consentErrorId = useId();
  const createPayment = useCreatePayment();
  const selected = products.find((product) => product.code === code) ?? products[0];
  const { reset } = createPayment;

  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) reset();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [reset]);

  const choose = (next: string) => {
    setCode(next);
    idempotenceKey.current = crypto.randomUUID();
    createPayment.reset();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!accepted) {
      setShowConsentError(true);
      return;
    }
    createPayment.mutate(
      { productCode: selected.code, idempotenceKey: idempotenceKey.current },
      {
        onSuccess: (payment) => {
          idempotenceKey.current = crypto.randomUUID();
          if (payment.confirmation_url) window.location.assign(payment.confirmation_url);
        },
      },
    );
  };

  const redirecting = createPayment.isSuccess && Boolean(createPayment.data.confirmation_url);
  const failure = createPayment.isError
    ? errorMessage(createPayment.error, "Не удалось создать платёж. Попробуйте ещё раз.")
    : createPayment.isSuccess && !createPayment.data.confirmation_url
      ? "Платёж создан, но ЮKassa не вернула ссылку на оплату. Попробуйте ещё раз."
      : null;

  return (
    <form className={styles.purchase} onSubmit={submit} noValidate>
      <fieldset className={styles.options}>
        <legend className={styles.visuallyHidden}>Что купить</legend>
        {products.map((product) => (
          <label key={product.code} className={styles.option}>
            <input
              type="radio"
              name="product"
              value={product.code}
              checked={product.code === selected.code}
              onChange={() => choose(product.code)}
            />
            <span className={styles.optionText}>
              <span className={styles.optionTitle}>{product.title}</span>
              <span className={styles.muted}>{productNote(product)}</span>
            </span>
            <span className={styles.optionPrice}>{formatRubles(product.price_rub)}</span>
          </label>
        ))}
      </fieldset>
      <div className={styles.consent}>
        <Checkbox
          checked={accepted}
          invalid={showConsentError && !accepted}
          aria-describedby={showConsentError && !accepted ? consentErrorId : undefined}
          onChange={(event) => {
            setAccepted(event.target.checked);
            setShowConsentError(false);
          }}
          label={
            <>
              Принимаю условия{" "}
              <a href="/legal/offer" target="_blank" rel="noreferrer">
                публичной оферты
              </a>
            </>
          }
        />
        {showConsentError && !accepted && (
          <p id={consentErrorId} className={styles.alert}>
            Чтобы перейти к оплате, примите условия оферты.
          </p>
        )}
        <p className={styles.muted}>
          Возврат денег по{" "}
          <a href="/legal/refund" target="_blank" rel="noreferrer">
            правилам возврата
          </a>
          .
        </p>
      </div>
      {failure && (
        <p className={styles.alert} role="alert">
          {failure}
        </p>
      )}
      <div>
        <Button type="submit" loading={createPayment.isPending || redirecting}>
          Оплатить {formatRubles(selected.price_rub)}
        </Button>
      </div>
    </form>
  );
}
