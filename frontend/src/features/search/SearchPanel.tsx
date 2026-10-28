import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { formatTimecode } from "../../lib/timecode";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Input";
import { Spinner } from "../../ui/Spinner";
import { HitSummary } from "./HitSummary";
import { buildMatcher } from "./matcher";
import { MIN_QUERY_LENGTH, searchErrorText, useDebouncedValue, useSearch } from "./queries";
import "./search.css";

export function momentsCount(count: number) {
  const tens = count % 100;
  const ones = count % 10;
  if (tens >= 11 && tens <= 14) return `${count} моментов`;
  if (ones === 1) return `${count} момент`;
  if (ones >= 2 && ones <= 4) return `${count} момента`;
  return `${count} моментов`;
}

type SearchPanelProps = {
  scope: { lectureId: string } | { courseId: string };
  children?: ReactNode;
  onActiveChange?: (active: boolean) => void;
};

export function SearchPanel({ scope, children, onActiveChange }: SearchPanelProps) {
  const [value, setValue] = useState("");
  const query = useDebouncedValue(value.trim(), 300);
  const search = useSearch(scope, query);
  const inCourse = "courseId" in scope;
  const active = query.length >= MIN_QUERY_LENGTH;
  const hits = active ? search.data : undefined;
  const matcher = useMemo(() => buildMatcher(query), [query]);
  const label = inCourse ? "Поиск по курсу" : "Поиск по лекции";

  useEffect(() => {
    onActiveChange?.(active);
  }, [active, onActiveChange]);

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

      {!active && children}
      <div className={active || !children ? "search__body" : "search__body search__body--idle"} aria-live="polite">
        {!active && !children && (
          <p className="search__note">Ищет по расшифровкам всех лекций курса и открывает запись на нужной минуте.</p>
        )}
        {active && search.isPending && <p className="search__note">Ищем…</p>}
        {active && search.isError && !hits && (
          <div className="search__error" role="alert">
            <p>{searchErrorText(search.error)}</p>
            <Button variant="secondary" size="sm" onClick={() => void search.refetch()}>
              Повторить
            </Button>
          </div>
        )}
        {hits && hits.length === 0 && !search.isPlaceholderData && (
          <p className="search__note">
            По запросу «{query}» ничего не нашлось. Попробуйте другие слова.
          </p>
        )}
        {hits && hits.length > 0 && (
          <>
            <p className="search__count">Найдено {momentsCount(hits.length)}</p>
            <ol className={search.isPlaceholderData ? "search__hits search__hits--stale" : "search__hits"}>
              {hits.map((hit) => (
                <li key={`${hit.lecture_id}-${hit.start}`}>
                  <Link className="search__hit" to={`/lectures/${hit.lecture_id}?t=${Math.floor(hit.start ?? 0)}`}>
                    <span className="search__time">{formatTimecode(hit.start ?? 0)}</span>
                    <span className="search__content">
                      {inCourse && <span className="search__lecture">{hit.lecture_title}</span>}
                      <HitSummary hit={hit} matcher={matcher} />
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
