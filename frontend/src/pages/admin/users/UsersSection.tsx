import { useId, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { Button } from "../../../ui/Button";
import { Input } from "../../../ui/Input";
import { Spinner } from "../../../ui/Spinner";
import { formatShortDate } from "../../account/format";
import shared from "../AdminPage.module.css";
import { useUserSearch } from "./api";
import styles from "./Users.module.css";

function SearchForm({ initial, onSearch }: { initial: string; onSearch: (value: string) => void }) {
  const inputId = useId();
  const hintId = useId();
  const [draft, setDraft] = useState(initial);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSearch(draft.trim());
  };

  return (
    <form className={styles.search} onSubmit={submit} role="search">
      <label className={styles.searchLabel} htmlFor={inputId}>
        Почта, Telegram id или @username
      </label>
      <Input
        id={inputId}
        type="search"
        value={draft}
        autoComplete="off"
        spellCheck={false}
        maxLength={320}
        aria-describedby={hintId}
        onChange={(event) => setDraft(event.target.value)}
      />
      <Button type="submit" disabled={draft.trim().length < 2}>
        Найти
      </Button>
      <p id={hintId} className={styles.searchHint}>
        По почте ищется часть адреса, по Telegram только точное совпадение. Каждый поиск и просмотр карточки
        попадает в журнал.
      </p>
    </form>
  );
}

export function UsersSection() {
  const titleId = useId();
  const [params, setParams] = useSearchParams();
  const query = (params.get("q") ?? "").trim();
  const { data, isFetching, isError, refetch } = useUserSearch(query);

  const search = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set("q", value);
    else next.delete("q");
    setParams(next);
  };

  const tooShort = query.length > 0 && query.length < 2;

  return (
    <section className={shared.panel} aria-labelledby={titleId} aria-busy={isFetching || undefined}>
      <div className={shared.panelHead}>
        <h2 id={titleId} className={shared.panelTitle}>
          Пользователи
        </h2>
        {data && query.length >= 2 && (
          <p className={shared.muted}>{data.length === 20 ? "Показаны первые 20" : `Найдено: ${data.length}`}</p>
        )}
      </div>
      <SearchForm key={query} initial={query} onSearch={search} />
      {tooShort && <p className={shared.muted}>Нужно хотя бы два символа.</p>}
      {query.length >= 2 && isFetching && !data && (
        <div className={shared.state}>
          <Spinner label="Ищем" />
        </div>
      )}
      {isError && (
        <div className={shared.state} role="alert">
          <p>Не удалось выполнить поиск.</p>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {query.length >= 2 && data && data.length === 0 && (
        <p className={shared.empty}>По запросу «{query}» никого нет. Проверьте адрес или поищите по Telegram.</p>
      )}
      {query.length >= 2 && data && data.length > 0 && (
        <ul className={styles.results}>
          {data.map((user) => (
            <li key={user.id}>
              <Link className={styles.result} to={`/admin/users/${user.id}`}>
                <span className={styles.resultName}>
                  {user.display_name.trim() || user.email || "Без имени"}
                  {user.is_admin && <span className={styles.mark}>Админ</span>}
                  {user.blocked && <span className={`${styles.mark} ${styles.markDanger}`}>Заблокирован</span>}
                </span>
                <span className={styles.resultMeta}>{user.email ?? "Без почты"}</span>
                <span className={styles.resultDate}>с {formatShortDate(user.created_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
