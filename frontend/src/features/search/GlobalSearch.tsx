import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { formatTimecode } from "../../lib/timecode";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Input";
import { Spinner } from "../../ui/Spinner";
import { buildMatcher, highlight } from "./highlight";
import { MIN_QUERY_LENGTH, useDebouncedValue, useSearch, type SearchHit } from "./queries";
import { momentsCount } from "./SearchPanel";
import "./search.css";

const kindLabels: Record<SearchHit["kind"], string> = {
  transcript: "Расшифровка",
  chapter: "Глава",
  summary: "Конспект",
};

type LectureGroup = { id: string; title: string; hits: SearchHit[] };

function groupByLecture(hits: SearchHit[]) {
  const groups = new Map<string, LectureGroup>();
  for (const hit of hits) {
    const group = groups.get(hit.lecture_id);
    if (group) group.hits.push(hit);
    else groups.set(hit.lecture_id, { id: hit.lecture_id, title: hit.lecture_title, hits: [hit] });
  }
  return [...groups.values()];
}

function hitLink(hit: SearchHit) {
  const base = `/lectures/${hit.lecture_id}`;
  if (hit.kind === "summary") return hit.section === null ? base : `${base}?section=${hit.section}`;
  return `${base}?t=${Math.floor(hit.start ?? 0)}`;
}

function hitPlace(hit: SearchHit) {
  const label = kindLabels[hit.kind];
  return hit.kind === "summary" || hit.start === null ? label : `${label}, ${formatTimecode(hit.start)}`;
}

export function GlobalSearch({ children }: { children: ReactNode }) {
  const [value, setValue] = useState("");
  const query = useDebouncedValue(value.trim(), 300);
  const search = useSearch({ all: true }, query);
  const active = query.length >= MIN_QUERY_LENGTH;
  const hits = active ? search.data : undefined;
  const groups = useMemo(() => groupByLecture(hits ?? []), [hits]);
  const matcher = useMemo(() => buildMatcher(query), [query]);

  return (
    <div className="search search--global">
      <form role="search" className="search__form" onSubmit={(event) => event.preventDefault()}>
        <Input
          type="search"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Где говорили про…"
          aria-label="Поиск по всем лекциям"
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
      <div className={active ? "search__body" : "search__body search__body--idle"} aria-live="polite">
        {active && search.isPending && <p className="search__note">Ищем…</p>}
        {active && search.isError && !search.isFetching && (
          <div className="search__error" role="alert">
            <p>Поиск не сработал. Проверьте соединение и попробуйте ещё раз.</p>
            <Button variant="secondary" size="sm" onClick={() => void search.refetch()}>
              Повторить
            </Button>
          </div>
        )}
        {hits && hits.length === 0 && !search.isPlaceholderData && (
          <p className="search__note">
            По запросу «{query}» ничего не нашлось ни в расшифровках, ни в главах, ни в конспектах. Попробуйте
            сказать иначе.
          </p>
        )}
        {hits && hits.length > 0 && (
          <>
            <p className="search__count">Найдено {momentsCount(hits.length)}</p>
            <div className={search.isPlaceholderData ? "search__groups search__hits--stale" : "search__groups"}>
              {groups.map((group) => (
                <section key={group.id} className="search__group" aria-labelledby={`search-group-${group.id}`}>
                  <h2 id={`search-group-${group.id}`} className="search__group-title">
                    <Link to={`/lectures/${group.id}`}>{group.title}</Link>
                  </h2>
                  <ol className="search__hits">
                    {group.hits.map((hit) => (
                      <li key={`${hit.kind}-${hit.start}-${hit.section}-${hit.text.slice(0, 24)}`}>
                        <Link className="search__hit search__hit--stacked" to={hitLink(hit)}>
                          <span className="search__place">{hitPlace(hit)}</span>
                          <span className="search__text">{highlight(hit.text, matcher)}</span>
                        </Link>
                      </li>
                    ))}
                  </ol>
                </section>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
