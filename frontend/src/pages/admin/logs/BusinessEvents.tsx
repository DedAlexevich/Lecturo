import { useId, useState } from "react";
import { Button } from "../../../ui/Button";
import { EmptyState } from "../../../ui/EmptyState";
import { Spinner } from "../../../ui/Spinner";
import { formatDateTime } from "../../account/format";
import styles from "./Logs.module.css";
import { eventKindLabels, eventKinds, pageSize, useBusinessEvents, type BusinessEventKind } from "./logsApi";

function describeDetails(details: Record<string, unknown>) {
  return Object.entries(details).map(([key, value]) => `${key}: ${String(value)}`);
}

export function BusinessEvents() {
  const kindId = useId();
  const [kind, setKind] = useState<BusinessEventKind | "">("");
  const [offset, setOffset] = useState(0);
  const { data, isPending, isError, refetch } = useBusinessEvents(kind, offset);

  return (
    <div className={styles.page}>
      <div className={styles.controls}>
        <div className={styles.controlWide}>
          <label className={styles.controlLabel} htmlFor={kindId}>
            Событие
          </label>
          <select
            id={kindId}
            className={styles.select}
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as BusinessEventKind | "");
              setOffset(0);
            }}
          >
            <option value="">Все события</option>
            {eventKinds.map((item) => (
              <option key={item} value={item}>
                {eventKindLabels[item]}
              </option>
            ))}
          </select>
        </div>
        <Button variant="secondary" onClick={() => void refetch()}>
          Обновить
        </Button>
      </div>

      {isPending && (
        <div className={styles.state}>
          <Spinner label="Загружаем события" />
        </div>
      )}
      {isError && (
        <div className={styles.state} role="alert">
          <p>Не удалось загрузить события.</p>
          <Button variant="secondary" size="sm" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && data.items.length === 0 && (
        <EmptyState title="Событий пока нет" description="Платежи, вебхуки, входы и удаления аккаунтов появятся здесь." />
      )}
      {data && data.items.length > 0 && (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Когда</th>
                  <th scope="col">Событие</th>
                  <th scope="col">Пользователь</th>
                  <th scope="col">Подробности</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td className={styles.nowrap}>{formatDateTime(item.created_at)}</td>
                    <td>{eventKindLabels[item.kind]}</td>
                    <td>{item.user_label || "—"}</td>
                    <td className={styles.details}>
                      {describeDetails(item.details).map((text) => (
                        <span key={text}>{text}</span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className={styles.pager}>
            <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(offset - pageSize)}>
              Назад
            </Button>
            <span className={styles.muted}>
              {offset + 1}–{offset + data.items.length} из {data.total}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={offset + pageSize >= data.total}
              onClick={() => setOffset(offset + pageSize)}
            >
              Дальше
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
