import { useId, type ReactNode } from "react";
import styles from "./SettingsSection.module.css";

type SettingsRowProps = {
  title: string;
  note?: string;
  children: ReactNode;
};

export function SettingsRow({ title, note, children }: SettingsRowProps) {
  const titleId = useId();

  return (
    <section className={styles.row} aria-labelledby={titleId}>
      <div className={styles.rowHead}>
        <h3 id={titleId} className={styles.rowTitle}>
          {title}
        </h3>
        {note && <p className={styles.muted}>{note}</p>}
      </div>
      <div className={styles.rowBody}>{children}</div>
    </section>
  );
}
