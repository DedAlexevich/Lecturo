import { useQueryClient } from "@tanstack/react-query";
import { getWebApp, openExternalLink } from "../../telegram/sdk";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useLocation } from "react-router";
import { useMe } from "../../app/useMe";
import { validateEmail } from "../auth/validation";
import { ReceiptEmailField } from "../../features/consent/ReceiptEmailField";
import { Button } from "../../ui/Button";
import { Checkbox } from "../../ui/Checkbox";
import styles from "./AccountPage.module.css";
import {
  errorMessage,
  paymentsQueryKey,
  quotaQueryKey,
  useCreatePayment,
  usePayments,
  useProducts,
  type Product,
} from "./billing";
import { formatRubles } from "./format";
import { SectionError, SectionLoading } from "./SectionState";
import { pollInterval, pollLimit } from "./usePaymentReturn";

export function PurchaseSection() {
  const titleId = useId();
  const { data: products, isPending, isError, refetch } = useProducts();
  const { data: me } = useMe();
  const { hash } = useLocation();
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (hash === "#purchase" && !isPending) sectionRef.current?.scrollIntoView({ block: "start" });
  }, [hash, isPending]);

  return (
    <section ref={sectionRef} id="purchase" className={styles.panel} aria-labelledby={titleId}>
      <div className={styles.sectionHead}>
        <h2 id={titleId} className={styles.sectionTitle}>
          Подписка и пакеты часов
        </h2>
        <p className={styles.muted}>
          {getWebApp()
            ? "Оплата картой через ЮKassa откроется в браузере. После оплаты вернитесь в Telegram, статус обновится здесь."
            : "Оплата картой через ЮKassa. После оплаты вы вернётесь в кабинет."}
        </p>
      </div>
      {isPending && <SectionLoading label="Загружаем тарифы" />}
      {isError && <SectionError message="Не удалось загрузить тарифы." onRetry={() => refetch()} />}
      {products && products.length === 0 && <p className={styles.muted}>Сейчас купить ничего нельзя.</p>}
      {products && products.length > 0 && (
        <PurchaseForm products={products} needsReceiptEmail={me ? !me.email : false} />
      )}
    </section>
  );
}

function productNote(product: Product) {
  if (product.kind === "subscription") return "Больше часов в неделю, квиз, памятка к экзамену и долгое хранение видео";
  if (!product.seconds) return "Не сгорает";
  const perHour = Math.round((product.price_rub / (product.seconds / 3600)) * 100) / 100;
  return `Не сгорает, ${formatRubles(perHour)} за час`;
}

function PurchaseForm({ products, needsReceiptEmail }: { products: Product[]; needsReceiptEmail: boolean }) {
  const [code, setCode] = useState(products[0].code);
  const [accepted, setAccepted] = useState(false);
  const [showConsentError, setShowConsentError] = useState(false);
  const [receiptEmail, setReceiptEmail] = useState("");
  const [receiptEmailError, setReceiptEmailError] = useState<string>();
  const idempotenceKey = useRef(crypto.randomUUID());
  const consentErrorId = useId();
  const createPayment = useCreatePayment();
  const queryClient = useQueryClient();
  const [returnedAt, setReturnedAt] = useState<number>();
  const createdId = createPayment.data?.id;
  const { data: payments } = usePayments(returnedAt && createdId ? pollInterval : false);
  const selected = products.find((product) => product.code === code) ?? products[0];
  const { reset } = createPayment;
  const settled = payments?.some((payment) => payment.id === createdId && payment.status !== "pending") ?? false;

  useEffect(() => {
    if (returnedAt === undefined) return;
    const timer = setTimeout(() => setReturnedAt(undefined), pollLimit);
    return () => clearTimeout(timer);
  }, [returnedAt]);

  useEffect(() => {
    if (settled) reset();
  }, [settled, reset]);

  useEffect(() => {
    const app = getWebApp();
    if (!app) return;
    const refresh = () => {
      if (document.visibilityState !== "visible") return;
      setReturnedAt(Date.now());
      queryClient.invalidateQueries({ queryKey: quotaQueryKey });
      queryClient.invalidateQueries({ queryKey: paymentsQueryKey });
    };
    app.onEvent("activated", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      app.offEvent("activated", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [queryClient]);

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
    if (getWebApp() && createPayment.data?.confirmation_url) {
      openExternalLink(createPayment.data.confirmation_url);
      return;
    }
    const emailError = needsReceiptEmail ? validateEmail(receiptEmail) : undefined;
    setReceiptEmailError(emailError);
    if (!accepted) setShowConsentError(true);
    if (emailError || !accepted) return;
    createPayment.mutate(
      {
        productCode: selected.code,
        idempotenceKey: idempotenceKey.current,
        receiptEmail: needsReceiptEmail ? receiptEmail.trim() : undefined,
      },
      {
        onSuccess: (payment) => {
          idempotenceKey.current = crypto.randomUUID();
          if (payment.confirmation_url && !getWebApp()) openExternalLink(payment.confirmation_url);
        },
      },
    );
  };

  const redirecting = !getWebApp() && createPayment.isSuccess && Boolean(createPayment.data.confirmation_url);
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
      {needsReceiptEmail && (
        <div className={styles.receiptEmail}>
          <ReceiptEmailField
            value={receiptEmail}
            error={receiptEmailError}
            onChange={(value) => {
              setReceiptEmail(value);
              setReceiptEmailError(undefined);
              idempotenceKey.current = crypto.randomUUID();
              if (createPayment.isError) createPayment.reset();
            }}
          />
        </div>
      )}
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
        {getWebApp() && createPayment.data?.confirmation_url ? (
          <Button type="button" onClick={() => openExternalLink(createPayment.data.confirmation_url!)}>
            Открыть оплату в браузере
          </Button>
        ) : (
          <Button type="submit" loading={createPayment.isPending || redirecting}>
            Оплатить {formatRubles(selected.price_rub)}
          </Button>
        )}
      </div>
    </form>
  );
}
