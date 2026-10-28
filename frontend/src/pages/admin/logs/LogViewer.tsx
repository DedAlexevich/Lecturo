import { useEffect, useId, useRef, useState } from "react";
import { Button } from "../../../ui/Button";
import { Input } from "../../../ui/Input";
import { Spinner } from "../../../ui/Spinner";
import { logLevels, logServices, useLogTail, type LogLevel, type LogLine, type LogService } from "./logsApi";
import styles from "./Logs.module.css";
import { streamLineLimit, useLogStream } from "./useLogStream";

const lineOptions = [100, 200, 500, 1000];

function lineClass(level: LogLevel | null) {
  if (level === "error" || level === "critical") return `${styles.line} ${styles.levelError}`;
  if (level === "warning") return `${styles.line} ${styles.levelWarning}`;
  if (level === "debug") return `${styles.line} ${styles.levelDebug}`;
  return styles.line;
}

const streamLabels = {
  idle: "",
  connecting: "Подключаемся",
  live: "Поток идёт",
  error: "",
} as const;

export function LogViewer() {
  const ids = { service: useId(), level: useId(), lines: useId(), query: useId() };
  const [service, setService] = useState<LogService>("api");
  const [level, setLevel] = useState<LogLevel | "">("");
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [lines, setLines] = useState(200);
  const [following, setFollowing] = useState(false);
  const [extra, setExtra] = useState<LogLine[]>([]);
  const view = useRef<HTMLPreElement>(null);

  const tail = useLogTail(service, level, query, lines);
  const baseLines = tail.data?.lines;
  const offset = tail.data?.offset ?? null;

  useEffect(() => {
    setExtra([]);
  }, [service, level, query, lines, tail.dataUpdatedAt]);

  const stream = useLogStream({
    service,
    level,
    query,
    active: following && tail.data !== undefined,
    startOffset: offset,
    onLines: (incoming, restarted) =>
      setExtra((current) => (restarted ? incoming : [...current, ...incoming]).slice(-streamLineLimit)),
  });

  const shown = baseLines ? [...baseLines, ...extra] : [];

  useEffect(() => {
    const element = view.current;
    if (element && following) element.scrollTop = element.scrollHeight;
  }, [shown.length, following]);

  useEffect(() => {
    const element = view.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [tail.dataUpdatedAt]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setQuery(draft.trim());
  };

  return (
    <div className={styles.page}>
      <form className={styles.controls} onSubmit={submit}>
        <div className={styles.control}>
          <label className={styles.controlLabel} htmlFor={ids.service}>
            Сервис
          </label>
          <select
            id={ids.service}
            className={styles.select}
            value={service}
            onChange={(event) => setService(event.target.value as LogService)}
          >
            {logServices.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.control}>
          <label className={styles.controlLabel} htmlFor={ids.level}>
            Уровень
          </label>
          <select
            id={ids.level}
            className={styles.select}
            value={level}
            onChange={(event) => setLevel(event.target.value as LogLevel | "")}
          >
            {logLevels.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.controlWide}>
          <label className={styles.controlLabel} htmlFor={ids.query}>
            Поиск по тексту
          </label>
          <Input id={ids.query} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={200} />
        </div>
        <div className={styles.control}>
          <label className={styles.controlLabel} htmlFor={ids.lines}>
            Строк
          </label>
          <select
            id={ids.lines}
            className={styles.select}
            value={lines}
            onChange={(event) => setLines(Number(event.target.value))}
          >
            {lineOptions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.actions}>
          <Button type="submit" variant="secondary">
            Найти
          </Button>
          <Button variant="secondary" onClick={() => void tail.refetch()} loading={tail.isFetching}>
            Обновить
          </Button>
          <Button variant={following ? "primary" : "secondary"} onClick={() => setFollowing((value) => !value)}>
            {following ? "Пауза" : "Следить"}
          </Button>
        </div>
      </form>

      <div>
        {following && stream.state !== "error" && <p className={styles.status}>{streamLabels[stream.state]}</p>}
        {stream.state === "error" && (
          <p className={styles.statusError} role="alert">
            {stream.message}
          </p>
        )}
        {tail.data && (
          <p className={styles.status}>
            Файл {service}.log, {Math.round(tail.data.size / 1024)} КБ. Секреты и адреса почты скрыты.
          </p>
        )}
      </div>

      {tail.isPending && (
        <div className={styles.state}>
          <Spinner label="Загружаем лог" />
        </div>
      )}
      {tail.isError && (
        <div className={styles.state} role="alert">
          <p>Лог недоступен: файла нет или он не читается.</p>
          <Button variant="secondary" size="sm" onClick={() => void tail.refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {tail.data && (
        <pre className={styles.log} ref={view} tabIndex={0} aria-label={`Лог ${service}`}>
          {shown.length === 0 ? "Подходящих строк нет" : null}
          {shown.map((line, index) => (
            <code key={index} className={lineClass(line.level)}>
              {line.text}
            </code>
          ))}
        </pre>
      )}
    </div>
  );
}
