import { Tabs } from "../../../ui/Tabs";
import { BusinessEvents } from "./BusinessEvents";
import { LogViewer } from "./LogViewer";
import styles from "./Logs.module.css";
import { ProcessingErrors } from "./ProcessingErrors";

export function AdminLogsPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h2>Логи и ошибки</h2>
        <p className={styles.muted}>Файлы сервисов, упавшие шаги обработки и журнал событий бизнеса.</p>
      </header>
      <Tabs
        label="Разделы логов"
        items={[
          { id: "logs", label: "Логи", panel: <LogViewer /> },
          { id: "errors", label: "Ошибки обработки", panel: <ProcessingErrors /> },
          { id: "events", label: "События бизнеса", panel: <BusinessEvents /> },
        ]}
      />
    </div>
  );
}
