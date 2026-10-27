import { useMe } from "../../app/useMe";
import { Spinner } from "../../ui/Spinner";
import styles from "./AccountPage.module.css";
import { PaymentsSection } from "./PaymentsSection";
import { PurchaseSection } from "./PurchaseSection";
import { QuotaSection } from "./QuotaSection";
import { SettingsSection } from "./SettingsSection";
import { usePaymentReturn } from "./usePaymentReturn";

export function AccountPage() {
  const { data: me } = useMe();
  const checkingPayment = usePaymentReturn();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1>Кабинет</h1>
        {me && <p className={styles.muted}>{[me.display_name.trim(), me.email].filter(Boolean).join(", ")}</p>}
      </header>
      {checkingPayment && (
        <p className={styles.notice} role="status">
          <Spinner size="sm" label="Проверяем оплату" />
          Проверяем оплату, это займёт несколько секунд.
        </p>
      )}
      <QuotaSection />
      <PurchaseSection />
      <PaymentsSection />
      <SettingsSection />
    </div>
  );
}
