import { openExternalLink } from "../../telegram/sdk";
import { useId } from "react";
import { EmptyState } from "../../ui/EmptyState";
import styles from "./AccountPage.module.css";
import { usePayments, useProducts, type Payment } from "./billing";
import { formatRubles, formatShortDate } from "./format";
import { SectionError, SectionLoading } from "./SectionState";

const statusLabels: Record<Payment["status"], string> = {
  pending: "Не оплачен",
  succeeded: "Оплачен",
  canceled: "Отменён",
};

const statusClasses: Record<Payment["status"], string> = {
  pending: styles.statusPending,
  succeeded: styles.statusSucceeded,
  canceled: styles.statusCanceled,
};

export function PaymentsSection() {
  const titleId = useId();
  const { data: payments, isPending, isError, refetch } = usePayments();
  const { data: products } = useProducts();
  const titles = new Map(products?.map((product) => [product.code, product.title]));

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        Платежи
      </h2>
      {isPending && <SectionLoading label="Загружаем платежи" />}
      {isError && <SectionError message="Не удалось загрузить платежи." onRetry={() => refetch()} />}
      {payments && payments.length === 0 && (
        <EmptyState title="Платежей пока нет" description="Здесь появятся покупки подписки и пакетов часов." />
      )}
      {payments && payments.length > 0 && (
        <table className={styles.payments}>
          <thead>
            <tr>
              <th scope="col">Дата</th>
              <th scope="col">Покупка</th>
              <th scope="col" className={styles.numeric}>
                Сумма
              </th>
              <th scope="col">Статус</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((payment) => (
              <tr key={payment.id}>
                <td className={styles.date}>{formatShortDate(payment.paid_at ?? payment.created_at)}</td>
                <td>{titles.get(payment.product_code) ?? payment.product_code}</td>
                <td className={styles.numeric}>{formatRubles(payment.amount_kopecks / 100)}</td>
                <td>
                  <span className={styles.status}>
                    <span className={statusClasses[payment.status]}>{statusLabels[payment.status]}</span>
                    {payment.status === "pending" && payment.confirmation_url && (
                      <a
                        href={payment.confirmation_url}
                        onClick={(event) => {
                          event.preventDefault();
                          openExternalLink(payment.confirmation_url!);
                        }}
                      >
                        Оплатить
                      </a>
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
