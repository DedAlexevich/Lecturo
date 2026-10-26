import { useMe } from "../../app/useMe";
import styles from "./AccountPage.module.css";
import { PurchaseSection } from "./PurchaseSection";
import { QuotaSection } from "./QuotaSection";

export function AccountPage() {
  const { data: me } = useMe();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1>Кабинет</h1>
        {me && <p className={styles.muted}>{me.email ? `${me.display_name}, ${me.email}` : me.display_name}</p>}
      </header>
      <QuotaSection />
      <PurchaseSection />
    </div>
  );
}
