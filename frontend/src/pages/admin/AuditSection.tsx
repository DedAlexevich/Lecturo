import { useId } from "react";
import { useSearchParams } from "react-router";
import { Button } from "../../ui/Button";
import { Spinner } from "../../ui/Spinner";
import styles from "./AdminPage.module.css";
import { auditPageSize, useAdmins, useAudit, type AdminAction, type AuditEntry } from "./api";

const actionLabels: Record<AdminAction, string> = {
  admin_granted: "Назначил администратора",
  admin_revoked: "Снял администратора",
};

const sourceLabels: Record<string, string> = {
  panel: "В панели",
  cli: "Командой на сервере",
  env: "Через INITIAL_ADMINS",
};

const dateTime = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isAction(value: string | null): value is AdminAction {
  return value !== null && value in actionLabels;
}

function describeDetails(details: AuditEntry["details"]) {
  return Object.entries(details).map(([key, value]) => {
    if (key === "source" && typeof value === "string") return sourceLabels[value] ?? value;
    return `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`;
  });
}

export function AuditSection() {
  const titleId = useId();
  const actionId = useId();
  const actorId = useId();
  const [params, setParams] = useSearchParams();
  const actionParam = params.get("action");
  const action = isAction(actionParam) ? actionParam : null;
  const actorParam = params.get("actor");
  const actor = actorParam !== null && uuidPattern.test(actorParam) ? actorParam : null;
  const page = Math.max(1, Number(params.get("page")) || 1);
  const { data, isPending, isError, isFetching, refetch } = useAudit({ action, actorId: actor, page });
  const { data: admins = [] } = useAdmins();

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const first = data && data.total > 0 ? (page - 1) * auditPageSize + 1 : 0;
  const last = data ? (page - 1) * auditPageSize + data.items.length : 0;
  const filtered = action !== null || actor !== null;

  return (
    <section className={styles.panel} aria-labelledby={titleId} aria-busy={isFetching || undefined}>
      <div className={styles.panelHead}>
        <h2 id={titleId} className={styles.panelTitle}>
          Журнал действий
        </h2>
        {data && (
          <p className={styles.muted}>
            {data.items.length === 0 ? "Записей нет" : `${first}–${last} из ${data.total}`}
          </p>
        )}
      </div>
      <div className={styles.filters}>
        <label className={styles.filter} htmlFor={actionId}>
          <span className={styles.filterLabel}>Действие</span>
          <select
            id={actionId}
            className={styles.select}
            value={action ?? ""}
            onChange={(event) => setFilter("action", event.target.value)}
          >
            <option value="">Все действия</option>
            {Object.entries(actionLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filter} htmlFor={actorId}>
          <span className={styles.filterLabel}>Кто</span>
          <select
            id={actorId}
            className={styles.select}
            value={actor ?? ""}
            onChange={(event) => setFilter("actor", event.target.value)}
          >
            <option value="">Все</option>
            {actor !== null && !admins.some((admin) => admin.id === actor) && (
              <option value={actor}>Бывший администратор</option>
            )}
            {admins.map((admin) => (
              <option key={admin.id} value={admin.id}>
                {admin.email ?? admin.display_name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {isPending && (
        <div className={styles.state}>
          <Spinner label="Загружаем журнал" />
        </div>
      )}
      {isError && (
        <div className={styles.state} role="alert">
          <p>Не удалось загрузить журнал.</p>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && data.items.length === 0 && (
        <p className={styles.empty}>
          {page > 1
            ? "На этой странице записей нет."
            : filtered
              ? "По этим условиям записей нет." : "Действий пока не было. Здесь появятся назначения и снятия администраторов."}
        </p>
      )}
      {data && data.items.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Когда</th>
              <th scope="col">Кто</th>
              <th scope="col">Что сделано</th>
              <th scope="col">Как</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((entry) => (
              <tr key={entry.id}>
                <td className={styles.when}>
                  <time dateTime={entry.created_at}>{dateTime.format(new Date(entry.created_at))}</time>
                </td>
                <td className={styles.who}>{entry.actor_label || <span className={styles.muted}>Сервер</span>}</td>
                <td>
                  <span className={styles.what}>{actionLabels[entry.action]}</span>
                  <span className={styles.subline}>{entry.target_label || entry.target_id || "—"}</span>
                </td>
                <td className={styles.how}>{describeDetails(entry.details).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && (data.total > auditPageSize || page > 1) && (
        <div className={styles.pager}>
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setFilter("page", String(page - 1))}>
            Назад
          </Button>
          <span className={styles.muted}>
            Страница {page} из {Math.max(1, Math.ceil(data.total / auditPageSize))}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={last >= data.total}
            onClick={() => setFilter("page", String(page + 1))}
          >
            Дальше
          </Button>
        </div>
      )}
    </section>
  );
}
