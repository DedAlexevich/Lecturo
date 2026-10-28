import { Fragment, useId, useState, type FormEvent } from "react";
import { Button } from "../../../ui/Button";
import { Field } from "../../../ui/Field";
import { Input } from "../../../ui/Input";
import { Spinner } from "../../../ui/Spinner";
import { useToast } from "../../../ui/Toast";
import { formatDate, formatDateTime, formatRubles, formatShortDate } from "../../account/format";
import shared from "../AdminPage.module.css";
import { errorMessage } from "../api";
import {
  useCreatePromo,
  useDisablePromo,
  usePromoCodes,
  usePromoRedemptions,
  type PromoCode,
  type PromoCreate,
  type PromoKind,
} from "./api";
import styles from "./Promo.module.css";
import { describeTerms, endOfMoscowDay, promoCodePattern, promoStatus, usageLabel } from "./terms";

const kindOptions: { id: PromoKind | "discount_rub"; label: string; amountLabel: string; min: number; max: number }[] = [
  { id: "hours", label: "Часы обработки", amountLabel: "Сколько часов", min: 1, max: 1000 },
  { id: "subscription_days", label: "Дни подписки", amountLabel: "Сколько дней", min: 1, max: 366 },
  { id: "discount", label: "Скидка в процентах", amountLabel: "Процент скидки", min: 1, max: 99 },
  { id: "discount_rub", label: "Скидка в рублях", amountLabel: "Сумма скидки, ₽", min: 1, max: 100000 },
];

const paymentLabels: Record<string, string> = {
  pending: "ждёт оплаты",
  succeeded: "оплачен",
  canceled: "отменён",
  refunded: "возвращён",
};

function isWhole(value: string, min: number, max: number) {
  const number = Number(value);
  return value !== "" && Number.isInteger(number) && number >= min && number <= max;
}

function buildBody(
  kind: (typeof kindOptions)[number]["id"],
  amount: number,
  fields: { code: string; maxUses: string; validUntil: string; note: string },
): PromoCreate {
  const base = {
    code: fields.code.trim() ? fields.code.trim().toUpperCase() : null,
    max_redemptions: fields.maxUses ? Number(fields.maxUses) : null,
    valid_until: fields.validUntil ? endOfMoscowDay(fields.validUntil) : null,
    note: fields.note.trim(),
  };
  if (kind === "hours") return { ...base, kind, hours: amount };
  if (kind === "subscription_days") return { ...base, kind, days: amount };
  if (kind === "discount") return { ...base, kind, discount_percent: amount };
  return { ...base, kind: "discount", discount_kopecks: amount * 100 };
}

function CreateForm() {
  const kindId = useId();
  const [kind, setKind] = useState<(typeof kindOptions)[number]["id"]>("hours");
  const [amount, setAmount] = useState("5");
  const [code, setCode] = useState("");
  const [maxUses, setMaxUses] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [note, setNote] = useState("");
  const create = useCreatePromo();
  const toast = useToast();
  const option = kindOptions.find((item) => item.id === kind) ?? kindOptions[0];
  const amountValid = isWhole(amount, option.min, option.max);
  const codeValid = code.trim() === "" || promoCodePattern.test(code.trim());
  const maxUsesValid = maxUses === "" || isWhole(maxUses, 1, 1_000_000);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!amountValid || !codeValid || !maxUsesValid) return;
    create.mutate(buildBody(kind, Number(amount), { code, maxUses, validUntil, note }), {
      onSuccess: (promo) => {
        toast.show(`Промокод ${promo.code} создан`, "success");
        setCode("");
        setNote("");
      },
    });
  };

  return (
    <form className={styles.createForm} onSubmit={submit} noValidate>
      <h3 className={styles.formTitle}>Новый промокод</h3>
      <div className={styles.formGrid}>
        <div className={shared.filter}>
          <label className={shared.filterLabel} htmlFor={kindId}>
            Что даёт
          </label>
          <select
            id={kindId}
            className={shared.select}
            value={kind}
            onChange={(event) => {
              const next = kindOptions.find((item) => item.id === event.target.value) ?? kindOptions[0];
              setKind(next.id);
              setAmount("");
            }}
          >
            {kindOptions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <Field
          label={option.amountLabel}
          error={amount !== "" && !amountValid ? `Целое число от ${option.min} до ${option.max}` : undefined}
        >
          {(control) => (
            <Input
              {...control}
              type="number"
              inputMode="numeric"
              min={option.min}
              max={option.max}
              step={1}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          )}
        </Field>
        <Field
          label="Код"
          hint="Пусто — сгенерируем. Латиница, цифры, - и _, от 4 до 32 знаков"
          error={codeValid ? undefined : "Только латиница, цифры, - и _, от 4 до 32 знаков"}
        >
          {(control) => (
            <Input
              {...control}
              value={code}
              maxLength={32}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setCode(event.target.value)}
            />
          )}
        </Field>
        <Field
          label="Сколько раз можно применить"
          hint="Пусто — без ограничения. Один человек — один раз"
          error={maxUsesValid ? undefined : "Целое число от 1"}
        >
          {(control) => (
            <Input
              {...control}
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={maxUses}
              onChange={(event) => setMaxUses(event.target.value)}
            />
          )}
        </Field>
        <Field label="Действует до" hint="Включительно, по Москве. Пусто — бессрочно">
          {(control) => (
            <Input {...control} type="date" value={validUntil} onChange={(event) => setValidUntil(event.target.value)} />
          )}
        </Field>
        <Field label="Заметка" hint="Для кого и зачем, видно только админам">
          {(control) => <Input {...control} value={note} maxLength={200} onChange={(event) => setNote(event.target.value)} />}
        </Field>
      </div>
      {create.isError && (
        <p className={shared.alert} role="alert">
          {errorMessage(create.error, "Не удалось создать промокод")}
        </p>
      )}
      <div>
        <Button type="submit" loading={create.isPending} disabled={!amountValid || !codeValid || !maxUsesValid}>
          Создать промокод
        </Button>
      </div>
    </form>
  );
}

function Redemptions({ promoId }: { promoId: string }) {
  const { data, isPending, isError, refetch } = usePromoRedemptions(promoId);

  if (isPending) return <Spinner size="sm" label="Загружаем применения" />;
  if (isError) {
    return (
      <div className={styles.redemptionsState} role="alert">
        <span>Не удалось загрузить применения.</span>
        <Button size="sm" variant="secondary" onClick={() => refetch()}>
          Повторить
        </Button>
      </div>
    );
  }
  if (data.length === 0) return <p className={shared.muted}>Промокод ещё никто не применял.</p>;
  return (
    <ul className={styles.redemptions}>
      {data.map((item) => (
        <li key={`${item.user_id}-${item.created_at}`}>
          <span className={shared.when}>{formatDateTime(item.created_at)}</span>
          <span className={styles.redemptionUser}>{item.user_label}</span>
          {item.payment_status && (
            <span className={shared.muted}>
              платёж {formatRubles((item.payment_amount_kopecks ?? 0) / 100)}, {paymentLabels[item.payment_status]}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function PromoRow({ promo, open, onToggle }: { promo: PromoCode; open: boolean; onToggle: () => void }) {
  const disable = useDisablePromo();
  const toast = useToast();
  const status = promoStatus(promo);
  const detailsId = useId();

  return (
    <Fragment>
      <tr>
        <td>
          <span className={styles.code}>{promo.code}</span>
          {promo.note && <span className={shared.subline}>{promo.note}</span>}
        </td>
        <td>{describeTerms(promo)}</td>
        <td className={styles.numeric}>{usageLabel(promo)}</td>
        <td className={shared.when}>{promo.valid_until ? `до ${formatDate(promo.valid_until)}` : "Бессрочно"}</td>
        <td>
          <span className={status === "Действует" ? undefined : shared.muted}>{status}</span>
          <span className={shared.subline}>с {formatShortDate(promo.created_at)}</span>
        </td>
        <td className={styles.rowActions}>
          <Button size="sm" variant="ghost" aria-expanded={open} aria-controls={detailsId} onClick={onToggle}>
            {open ? "Скрыть" : "Кто применил"}
          </Button>
          {!promo.disabled_at && (
            <Button
              size="sm"
              variant="secondary"
              loading={disable.isPending}
              onClick={() =>
                disable.mutate(promo.id, {
                  onSuccess: () => toast.show(`Промокод ${promo.code} отключён`, "success"),
                  onError: (error) => toast.show(errorMessage(error, "Не удалось отключить промокод"), "error"),
                })
              }
            >
              Отключить
            </Button>
          )}
        </td>
      </tr>
      {open && (
        <tr id={detailsId} className={styles.detailsRow}>
          <td colSpan={6}>
            <Redemptions promoId={promo.id} />
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export function PromoSection() {
  const titleId = useId();
  const { data, isPending, isError, refetch } = usePromoCodes();
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <section className={shared.panel} aria-labelledby={titleId}>
      <div className={shared.panelHead}>
        <h2 id={titleId} className={shared.panelTitle}>
          Промокоды
        </h2>
        {data && <p className={shared.muted}>Всего: {data.length}</p>}
      </div>
      <CreateForm />
      {isPending && (
        <div className={shared.state}>
          <Spinner label="Загружаем промокоды" />
        </div>
      )}
      {isError && (
        <div className={shared.state} role="alert">
          <p>Не удалось загрузить промокоды.</p>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && data.length === 0 && <p className={shared.empty}>Промокодов пока нет.</p>}
      {data && data.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={shared.table}>
            <thead>
              <tr>
                <th scope="col">Код</th>
                <th scope="col">Что даёт</th>
                <th scope="col" className={styles.numeric}>
                  Применений
                </th>
                <th scope="col">Срок</th>
                <th scope="col">Статус</th>
                <th scope="col">
                  <span className={styles.visuallyHidden}>Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((promo) => (
                <PromoRow
                  key={promo.id}
                  promo={promo}
                  open={openId === promo.id}
                  onToggle={() => setOpenId(openId === promo.id ? null : promo.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
