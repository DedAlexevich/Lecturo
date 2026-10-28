import { useId, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { Button } from "../../../ui/Button";
import { Input } from "../../../ui/Input";
import { Spinner } from "../../../ui/Spinner";
import { formatDate, formatShortDate } from "../../account/format";
import shared from "../AdminPage.module.css";
import { useUserSearch, type UserBrief } from "./api";
import { formatHours } from "./format";
import { UserActionButtons, UserActionDialog, type ActionKind } from "./UserActionDialog";
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
        Почта, имя, Telegram id или @username
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
        Подойдёт часть почты, имени или username, регистр не важен. Telegram id нужен целиком. Каждый поиск и
        просмотр карточки попадает в журнал.
      </p>
    </form>
  );
}

const searchLimit = 20;

function nameOf(user: UserBrief) {
  return user.display_name.trim() || user.email || "Без имени";
}

function planOf(user: UserBrief) {
  const plan = user.subscription_until ? `Подписка до ${formatDate(user.subscription_until)}` : "Бесплатный";
  return user.package_left_sec > 0 ? `${plan}, пакет ${formatHours(user.package_left_sec)}` : plan;
}

type Picked = { user: UserBrief; kind: ActionKind };

function ResultRow({ user, meId, onPick }: { user: UserBrief; meId: string; onPick: (picked: Picked) => void }) {
  return (
    <li className={styles.resultRow}>
      <Link className={styles.result} to={`/admin/users/${user.id}`}>
        <span className={styles.resultName}>
          {nameOf(user)}
          {user.is_admin && <span className={styles.mark}>Админ</span>}
          {user.blocked && <span className={`${styles.mark} ${styles.markDanger}`}>Заблокирован</span>}
        </span>
        <span className={styles.resultMeta}>
          {user.email ?? "Без почты"}
          {user.telegram_username && ` · @${user.telegram_username}`}
        </span>
        <span className={styles.resultPlan}>{planOf(user)}</span>
        <span className={styles.resultDate}>с {formatShortDate(user.created_at)}</span>
      </Link>
      <div className={styles.resultActions}>
        <UserActionButtons
          userId={user.id}
          meId={meId}
          isAdmin={user.is_admin}
          blocked={user.blocked}
          onPick={(kind) => onPick({ user, kind })}
        />
      </div>
    </li>
  );
}

export function UsersSection({ meId }: { meId: string }) {
  const titleId = useId();
  const [params, setParams] = useSearchParams();
  const query = (params.get("q") ?? "").trim();
  const { data, isFetching, isError, refetch } = useUserSearch(query);
  const [picked, setPicked] = useState<Picked | null>(null);

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
          <p className={shared.muted}>{data.length === searchLimit ? `Показаны первые ${searchLimit}` : `Найдено: ${data.length}`}</p>
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
        <p className={shared.empty}>По запросу «{query}» никого нет. Попробуйте другую часть почты, имени или username.</p>
      )}
      {query.length >= 2 && data && data.length > 0 && (
        <ul className={styles.results}>
          {data.map((user) => (
            <ResultRow key={user.id} user={user} meId={meId} onPick={setPicked} />
          ))}
        </ul>
      )}
      <UserActionDialog
        userId={picked?.user.id ?? ""}
        userName={picked ? nameOf(picked.user) : ""}
        kind={picked?.kind ?? null}
        onClose={() => setPicked(null)}
      />
    </section>
  );
}
