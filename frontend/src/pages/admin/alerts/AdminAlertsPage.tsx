import { useState } from "react";
import { Link } from "react-router";
import { telegramBotUrl } from "../../../telegram/bot";
import { Button } from "../../../ui/Button";
import { Checkbox } from "../../../ui/Checkbox";
import { Spinner } from "../../../ui/Spinner";
import { useToast } from "../../../ui/Toast";
import { errorMessage } from "../api";
import styles from "./Alerts.module.css";
import {
  alertKinds,
  useAlertSettings,
  useSaveAlertSettings,
  useSendTestAlert,
  type AlertKind,
  type AlertSettings,
  type AlertSettingsInput,
} from "./alertsApi";

const telegramStates: Record<AlertSettings["telegram"], string> = {
  ready: "Алерты приходят вам в Telegram от бота Lecturo.",
  not_linked: "Telegram не привязан, алерты вам не приходят. Привяжите его в кабинете.",
  start_required: "Telegram привязан, но бот ещё не запущен. Откройте бота и нажмите Start.",
  blocked: "Бот остановлен, алерты не доходят. Откройте бота и нажмите Start.",
};

function sameSettings(left: AlertSettingsInput, right: AlertSettingsInput) {
  return (
    left.enabled === right.enabled &&
    left.recoveries === right.recoveries &&
    left.kinds.length === right.kinds.length &&
    left.kinds.every((kind) => right.kinds.includes(kind))
  );
}

function AlertsForm({ saved }: { saved: AlertSettings }) {
  const [draft, setDraft] = useState<AlertSettingsInput>({
    enabled: saved.enabled,
    kinds: saved.kinds,
    recoveries: saved.recoveries,
  });
  const save = useSaveAlertSettings();
  const toast = useToast();
  const changed = !sameSettings(draft, saved);

  const toggleKind = (kind: AlertKind) =>
    setDraft((current) => ({
      ...current,
      kinds: current.kinds.includes(kind) ? current.kinds.filter((item) => item !== kind) : [...current.kinds, kind],
    }));

  const submit = () =>
    save.mutate(draft, {
      onSuccess: () => toast.show("Настройки алертов сохранены", "success"),
      onError: (error) => toast.show(errorMessage(error, "Не удалось сохранить настройки"), "error"),
    });

  return (
    <form
      className={styles.panel}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Checkbox
        label={<span className={styles.strong}>Получать алерты</span>}
        checked={draft.enabled}
        onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
      />
      <fieldset className={styles.kinds} disabled={!draft.enabled}>
        <legend className={styles.legend}>Какие алерты присылать</legend>
        {alertKinds.map(({ kind, title, when }) => (
          <div key={kind} className={styles.kind}>
            <Checkbox
              label={title}
              checked={draft.kinds.includes(kind)}
              onChange={() => toggleKind(kind)}
              aria-describedby={`alert-kind-${kind}`}
            />
            <p id={`alert-kind-${kind}`} className={styles.when}>
              {when}
            </p>
          </div>
        ))}
      </fieldset>
      <Checkbox
        label="Сообщать, когда проблема ушла"
        checked={draft.recoveries}
        disabled={!draft.enabled}
        onChange={(event) => setDraft({ ...draft, recoveries: event.target.checked })}
      />
      <div className={styles.formActions}>
        <Button type="submit" loading={save.isPending} disabled={!changed}>
          Сохранить
        </Button>
        {changed && <span className={styles.muted}>Есть несохранённые изменения</span>}
      </div>
    </form>
  );
}

function TelegramStatus({ state }: { state: AlertSettings["telegram"] }) {
  const test = useSendTestAlert();
  const toast = useToast();
  const ready = state === "ready";

  return (
    <section className={ready ? styles.status : styles.statusWarning} aria-label="Доставка алертов">
      <p>{telegramStates[state]}</p>
      <div className={styles.statusActions}>
        {ready && (
          <Button
            variant="secondary"
            size="sm"
            loading={test.isPending}
            onClick={() =>
              test.mutate(undefined, {
                onSuccess: () => toast.show("Тестовый алерт придёт через несколько секунд", "success"),
                onError: (error) => toast.show(errorMessage(error, "Не удалось отправить тестовый алерт"), "error"),
              })
            }
          >
            Прислать тестовый алерт
          </Button>
        )}
        {state === "not_linked" && (
          <Link className="button button--secondary button--sm" to="/account">
            Открыть кабинет
          </Link>
        )}
        {(state === "start_required" || state === "blocked") && telegramBotUrl && (
          <a className="button button--secondary button--sm" href={telegramBotUrl} target="_blank" rel="noopener noreferrer">
            Открыть бота
          </a>
        )}
      </div>
    </section>
  );
}

export function AdminAlertsPage() {
  const { data, isPending, isError, refetch } = useAlertSettings();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h2>Алерты в Telegram</h2>
        <p className={styles.muted}>
          Сообщения о сбоях сервера, очереди, бэкапах и платежах. Каждый администратор настраивает их для себя, здесь
          или в боте командой /alerts.
        </p>
      </header>

      {isPending && <Spinner label="Загрузка настроек" />}
      {isError && (
        <div className={styles.statusWarning} role="alert">
          <p>Не удалось загрузить настройки алертов.</p>
          <div>
            <Button size="sm" variant="secondary" onClick={() => void refetch()}>
              Повторить
            </Button>
          </div>
        </div>
      )}
      {data && (
        <>
          <TelegramStatus state={data.telegram} />
          <div className={styles.layout}>
            <AlertsForm key={JSON.stringify(data)} saved={data} />
            <aside className={styles.preview} aria-label="Как выглядит алерт">
              <h3>Как приходит алерт</h3>
              <div className={styles.message}>
                <strong>Алерт: Ошибки вебхуков ЮKassa</strong>
                <span>Вебхук ЮKassa, платёж 2f9a…: ЮKassa не отвечает (повторов: 3)</span>
                <span>Вебхук ЮKassa, платёж 7c01…: неверная сумма</span>
              </div>
              <p className={styles.muted}>
                Повторы одного типа бот собирает в одно сообщение и присылает не чаще раза в 15 минут, если на сервере не задан другой интервал. Сообщение о
                восстановлении приходит сразу.
              </p>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
