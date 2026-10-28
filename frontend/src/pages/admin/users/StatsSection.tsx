import { useId, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { Button } from "../../../ui/Button";
import { Input } from "../../../ui/Input";
import { Spinner } from "../../../ui/Spinner";
import { formatDateTime, formatRubles } from "../../account/format";
import shared from "../AdminPage.module.css";
import { errorMessage } from "../api";
import { useStats, type Stats, type StatsDay } from "./api";
import { formatCount, formatHours, kopecksToRubles } from "./format";
import { labelEvery, lastDays, niceScale, periodProblem, readPeriod, type Period } from "./stats";
import styles from "./Users.module.css";

type Metric = Exclude<keyof StatsDay, "day">;

type MetricView = { id: Metric; label: string; format: (value: number) => string; unit?: number };

const metrics: MetricView[] = [
  { id: "new_users", label: "Новые пользователи", format: formatCount },
  { id: "lectures", label: "Лекции", format: formatCount },
  { id: "processed_seconds", label: "Часы обработки", format: formatHours, unit: 3600 },
  { id: "failed_lectures", label: "Ошибки обработки", format: formatCount },
  { id: "payments", label: "Платежи", format: formatCount },
  { id: "revenue_kopecks", label: "Выручка", format: (value) => formatRubles(kopecksToRubles(value)) },
];

const presets = [7, 30, 90];

const dayLabel = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });
const dayFull = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

function formatDay(value: string, full = false) {
  return (full ? dayFull : dayLabel).format(new Date(`${value}T00:00:00Z`)).replace(" г.", "");
}

function PeriodForm({ period, onApply }: { period: Period; onApply: (period: Period) => void }) {
  const fromId = useId();
  const toId = useId();
  const [draft, setDraft] = useState(period);
  const problem = periodProblem(draft);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (problem === null) onApply(draft);
  };

  return (
    <form className={styles.periodForm} onSubmit={submit}>
      <div className={styles.presets} role="group" aria-label="Быстрый выбор периода">
        {presets.map((days) => {
          const preset = lastDays(days, new Date());
          const active = preset.from === period.from && preset.to === period.to;
          return (
            <Button
              key={days}
              size="sm"
              variant={active ? "primary" : "secondary"}
              aria-pressed={active}
              onClick={() => onApply(preset)}
            >
              {days} дней
            </Button>
          );
        })}
      </div>
      <div className={styles.periodFields}>
        <label className={styles.periodField} htmlFor={fromId}>
          <span className={shared.filterLabel}>С</span>
          <Input
            id={fromId}
            type="date"
            value={draft.from}
            onChange={(event) => setDraft({ ...draft, from: event.target.value })}
          />
        </label>
        <label className={styles.periodField} htmlFor={toId}>
          <span className={shared.filterLabel}>По</span>
          <Input id={toId} type="date" value={draft.to} onChange={(event) => setDraft({ ...draft, to: event.target.value })} />
        </label>
        <Button type="submit" size="sm" variant="secondary" disabled={problem !== null}>
          Показать
        </Button>
      </div>
      {problem && draft.from !== "" && draft.to !== "" && (
        <p className={shared.alert} role="alert">
          {problem}
        </p>
      )}
    </form>
  );
}

function Totals({ stats }: { stats: Stats }) {
  const { totals } = stats;
  return (
    <dl className={styles.totals}>
      {metrics.map((metric) => (
        <div key={metric.id} className={styles.total}>
          <dt>{metric.label}</dt>
          <dd className={styles.totalValue}>{metric.format(totals[metric.id])}</dd>
        </div>
      ))}
      <div className={styles.total}>
        <dt>Возвраты</dt>
        <dd className={styles.totalValue}>
          {formatCount(totals.refunds)}
          {totals.refunds > 0 && (
            <span className={styles.totalNote}>{formatRubles(kopecksToRubles(totals.refunded_kopecks))}</span>
          )}
        </dd>
      </div>
    </dl>
  );
}

const chart = { width: 720, height: 220, left: 72, bottom: 28, top: 8 };

function DayChart({ days, metric }: { days: StatsDay[]; metric: MetricView }) {
  const unit = metric.unit ?? 1;
  const values = days.map((day) => day[metric.id]);
  const scale = niceScale(Math.max(...values, 0) / unit);
  const plotWidth = chart.width - chart.left;
  const plotHeight = chart.height - chart.bottom - chart.top;
  const slot = plotWidth / days.length;
  const barWidth = Math.max(1, Math.min(slot * 0.7, 28));
  const every = labelEvery(days.length);
  const y = (value: number) => chart.top + plotHeight - (value / unit / scale.top) * plotHeight;

  return (
    <svg
      className={styles.chart}
      viewBox={`0 0 ${chart.width} ${chart.height}`}
      role="img"
      aria-label={`${metric.label} по дням, всего ${metric.format(values.reduce((sum, value) => sum + value, 0))}`}
    >
      {scale.ticks.map((tick) => (
        <g key={tick}>
          <line className={styles.chartGrid} x1={chart.left} x2={chart.width} y1={y(tick * unit)} y2={y(tick * unit)} />
          <text className={styles.chartTick} x={chart.left - 8} y={y(tick * unit)} textAnchor="end" dominantBaseline="middle">
            {metric.format(tick * unit)}
          </text>
        </g>
      ))}
      {days.map((day, index) => {
        const value = day[metric.id];
        const x = chart.left + slot * index + (slot - barWidth) / 2;
        return (
          <g key={day.day}>
            {value > 0 && (
              <rect className={styles.chartBar} x={x} y={y(value)} width={barWidth} height={y(0) - y(value)}>
                <title>
                  {formatDay(day.day, true)}: {metric.format(value)}
                </title>
              </rect>
            )}
            {index % every === 0 && (
              <text className={styles.chartTick} x={x + barWidth / 2} y={chart.height - 8} textAnchor="middle">
                {formatDay(day.day)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function DaysTable({ days }: { days: StatsDay[] }) {
  return (
    <details className={styles.daysDetails}>
      <summary>Таблица по дням</summary>
      <div className={styles.tableWrap}>
        <table className={styles.dataTable}>
          <thead>
            <tr>
              <th scope="col">День</th>
              {metrics.map((metric) => (
                <th key={metric.id} scope="col" className={styles.numeric}>
                  {metric.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...days].reverse().map((day) => (
              <tr key={day.day}>
                <td className={shared.when}>{formatDay(day.day, true)}</td>
                {metrics.map((metric) => (
                  <td key={metric.id} className={styles.numeric}>
                    {metric.format(day[metric.id])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function StatsView({ stats }: { stats: Stats }) {
  const [metricId, setMetricId] = useState<Metric>("new_users");
  const metric = metrics.find((item) => item.id === metricId) ?? metrics[0];

  return (
    <>
      <Totals stats={stats} />
      <div className={styles.chartBlock}>
        <div className={styles.metricSwitch} role="group" aria-label="Что показать на графике">
          {metrics.map((item) => (
            <Button
              key={item.id}
              size="sm"
              variant={item.id === metricId ? "primary" : "ghost"}
              aria-pressed={item.id === metricId}
              onClick={() => setMetricId(item.id)}
            >
              {item.label}
            </Button>
          ))}
        </div>
        <DayChart days={stats.days} metric={metric} />
      </div>
      <DaysTable days={stats.days} />
    </>
  );
}

export function StatsSection() {
  const titleId = useId();
  const [params, setParams] = useSearchParams();
  const period = readPeriod(params, lastDays(30, new Date()));
  const { data, isPending, isFetching, isError, error, refetch } = useStats(period.from, period.to);

  const apply = (next: Period) => {
    const updated = new URLSearchParams(params);
    updated.set("from", next.from);
    updated.set("to", next.to);
    setParams(updated);
  };

  return (
    <section className={shared.panel} aria-labelledby={titleId} aria-busy={isFetching || undefined}>
      <div className={shared.panelHead}>
        <h2 id={titleId} className={shared.panelTitle}>
          Статистика с {formatDay(period.from, true)} по {formatDay(period.to, true)}
        </h2>
        {data && <p className={shared.muted}>Посчитано {formatDateTime(data.generated_at)}, обновляется раз в 5 минут</p>}
      </div>
      <PeriodForm key={`${period.from}:${period.to}`} period={period} onApply={apply} />
      {isPending && (
        <div className={shared.state}>
          <Spinner label="Считаем" />
        </div>
      )}
      {isError && (
        <div className={shared.state} role="alert">
          <p>{errorMessage(error, "Не удалось загрузить статистику.")}</p>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && <StatsView stats={data} />}
    </section>
  );
}
