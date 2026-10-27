import { useMemo, useState } from "react";
import { Link } from "react-router";
import { formatTimecode } from "../../pages/lecture/time";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Input";
import { Spinner } from "../../ui/Spinner";
import { buildMatcher, highlight } from "./highlight";
import { MIN_QUERY_LENGTH, useDebouncedValue, useSearch, type SearchScope } from "./queries";
import "./search.css";

function fragmentsCount(count: number) {
  const tens = count % 100;
  const ones = count % 10;
  if (tens >= 11 && tens <= 14) return `${count} фрагментов`;
  if (ones === 1) return `${count} фрагмент`;
  if (ones >= 2 && ones <= 4) return `${count} фрагмента`;
  return `${count} фрагментов`;
}

export function SearchPanel({ scope }: { scope: SearchScope }) {
  const [value, setValue] = useState("");
  const query = useDebouncedValue(value.trim(), 300);
  const search = useSearch(scope, query);
  const inCourse = "courseId" in scope;
  const active = query.length >= MIN_QUERY_LENGTH;
  const hits = active ? search.data : undefined;
  const matcher = useMemo(() => buildMatcher(query), [query]);
  const label = inCourse ? "Поиск по курсу" : "Поиск по лекции";

  return (
    <div className={inCourse ? "search search--course" : "search search--lecture"}>
      <form role="search" className="search__form" onSubmit={(event) => event.preventDefault()}>
        <Input
          type="search"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={inCourse ? "Где объясняли…" : "Найти в лекции"}
          aria-label={label}
          maxLength={200}
          enterKeyHint="search"
        />
        {search.isFetching && active && (
          <span className="search__spinner">
            <Spinner size="sm" label="Ищем" />
          </span>
        )}
      </form>

      <div className="search__body" aria-live="polite">
        {!active && (
          <p className="search__note">
            {inCourse
              ? "Ищет по расшифровкам всех лекций курса и открывает запись на нужной минуте."
              : "Ищет по расшифровке и переносит видео к найденному месту."}
          </p>
        )}
        {active && search.isPending && <p className="search__note">Ищем…</p>}
        {active && search.isError && !hits && (
          <div className="search__error" role="alert">
            <p>Поиск не сработал. Проверьте соединение и попробуйте ещё раз.</p>
            <Button variant="secondary" size="sm" onClick={() => void search.refetch()}>
              Повторить
            </Button>
          </div>
        )}
        {hits && hits.length === 0 && (
          <p className="search__note">
            По запросу «{query}» ничего не нашлось. Попробуйте другие слова.
          </p>
        )}
        {hits && hits.length > 0 && (
          <>
            <p className="search__count">Найдено {fragmentsCount(hits.length)}</p>
            <ol className={search.isPlaceholderData ? "search__hits search__hits--stale" : "search__hits"}>
              {hits.map((hit) => (
                <li key={`${hit.lecture_id}-${hit.start}`}>
                  <Link className="search__hit" to={`/lectures/${hit.lecture_id}?t=${Math.floor(hit.start)}`}>
                    <span className="search__time">{formatTimecode(hit.start)}</span>
                    <span className="search__content">
                      {inCourse && <span className="search__lecture">{hit.lecture_title}</span>}
                      <span className="search__text">{highlight(hit.text, matcher)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
