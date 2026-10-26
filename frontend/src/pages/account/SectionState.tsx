import { Button } from "../../ui/Button";
import { Spinner } from "../../ui/Spinner";
import styles from "./AccountPage.module.css";

export function SectionLoading({ label }: { label: string }) {
  return (
    <div className={styles.state}>
      <Spinner label={label} />
    </div>
  );
}

export function SectionError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className={styles.state} role="alert">
      <p>{message}</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        Повторить
      </Button>
    </div>
  );
}
