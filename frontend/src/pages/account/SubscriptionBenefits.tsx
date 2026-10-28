import { useState } from "react";
import { formatDuration } from "../../lib/duration";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { useQuota, type Product } from "./billing";
import { formatDays, formatRubles } from "./format";
import { freePlan, subscriptionPlan } from "./plans";
import styles from "./SubscriptionBenefits.module.css";

type Row = { label: string; free: string | null; subscription: string };

export function SubscriptionBenefits({ products, onChoose }: { products: Product[]; onChoose: (code: string) => void }) {
  const [open, setOpen] = useState(false);
  const { data: quota } = useQuota();
  const subscription = products.find((product) => product.kind === "subscription");
  if (!subscription) return null;

  const subscribed = Boolean(quota?.subscription_until);
  const freeWeekly = quota && !subscribed ? quota.weekly_limit_sec : freePlan.weeklySeconds;
  const subscriptionWeekly = quota && subscribed ? quota.weekly_limit_sec : subscriptionPlan.weeklySeconds;

  const rows: Row[] = [
    { label: "Недельный лимит", free: formatDuration(freeWeekly, "down"), subscription: formatDuration(subscriptionWeekly, "down") },
    { label: "Квиз по лекции", free: null, subscription: "Есть" },
    { label: "Памятка к экзамену", free: null, subscription: "Есть" },
    { label: "Чат по лекции", free: null, subscription: "Есть" },
    {
      label: "Хранение видео",
      free: formatDays(freePlan.videoRetentionDays),
      subscription: formatDays(subscriptionPlan.videoRetentionDays),
    },
  ];

  const choose = () => {
    onChoose(subscription.code);
    setOpen(false);
  };

  return (
    <>
      <div>
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
          Что даёт подписка
        </Button>
      </div>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Что даёт подписка"
        className={styles.dialog}
        actions={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Закрыть
            </Button>
            <Button onClick={choose}>Выбрать подписку</Button>
          </>
        }
      >
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">
                <span className={styles.visuallyHidden}>Что входит</span>
              </th>
              <th scope="col" className={styles.value}>
                Без подписки
                {quota && !subscribed && <span className={styles.current}>сейчас у вас</span>}
              </th>
              <th scope="col" className={styles.value}>
                С подпиской
                {subscribed && <span className={styles.current}>сейчас у вас</span>}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td className={styles.value}>
                  {row.free ?? (
                    <span className={styles.missing}>
                      <span aria-hidden="true">—</span>
                      <span className={styles.visuallyHidden}>Нет</span>
                    </span>
                  )}
                </td>
                <td className={`${styles.value} ${styles.included}`}>{row.subscription}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={styles.price}>
          {subscription.title}, {formatRubles(subscription.price_rub)}
        </p>
      </Dialog>
    </>
  );
}
