import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";
import "./UiPage.css";

const colorGroups: { title: string; tokens: string[] }[] = [
  { title: "Фон и поверхности", tokens: ["bg", "surface", "surface-sunken", "border", "border-strong"] },
  { title: "Текст", tokens: ["text", "text-muted"] },
  { title: "Акцент", tokens: ["accent", "accent-hover", "accent-soft", "on-accent"] },
  { title: "Состояния", tokens: ["success", "warning", "danger"] },
];

const textSizes = [
  { token: "3xl", sample: "Конспект лекции", display: true },
  { token: "2xl", sample: "Основы термодинамики", display: true },
  { token: "xl", sample: "Второе начало и энтропия", display: true },
  { token: "lg", sample: "Энтропия замкнутой системы не убывает" },
  { token: "base", sample: "Преподаватель разбирает цикл Карно и объясняет, почему КПД не может быть равен единице." },
  { token: "sm", sample: "Загружено 12 октября, длительность 1 ч 24 мин" },
  { token: "xs", sample: "Таймкод 00:42:17" },
];

const spaces = [1, 2, 3, 4, 5, 6, 7, 8];
const radii = ["sm", "md", "lg", "pill"];
const shadows = [1, 2, 3];

export function UiPage() {
  return (
    <main className="ui-page">
      <header className="ui-page__header">
        <Logo size="lg" />
        <ThemeToggle />
      </header>

      <section className="ui-section">
        <h2>Цвета</h2>
        {colorGroups.map((group) => (
          <div key={group.title} className="ui-group">
            <h3>{group.title}</h3>
            <ul className="ui-swatches">
              {group.tokens.map((token) => (
                <li key={token} className="ui-swatch">
                  <span className="ui-swatch__color" style={{ background: `var(--color-${token})` }} />
                  <code>--color-{token}</code>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className="ui-section">
        <h2>Типографика</h2>
        <p className="ui-note">Заголовки и логотип набраны шрифтом с засечками, текст интерфейса остаётся без засечек.</p>
        <ul className="ui-type">
          {textSizes.map((item) => (
            <li key={item.token} className="ui-type__row">
              <code>--text-{item.token}</code>
              <span
                style={{
                  fontSize: `var(--text-${item.token})`,
                  fontFamily: item.display ? "var(--font-display)" : undefined,
                  fontWeight: item.display ? "var(--weight-semibold)" : undefined,
                }}
              >
                {item.sample}
              </span>
            </li>
          ))}
        </ul>
        <p className="ui-mono">
          <code>Моноширинный: 00:42:17 · 128 КБ</code>
        </p>
      </section>

      <section className="ui-section">
        <h2>Отступы</h2>
        <ul className="ui-spaces">
          {spaces.map((step) => (
            <li key={step} className="ui-space">
              <code>--space-{step}</code>
              <span className="ui-space__bar" style={{ width: `var(--space-${step})` }} />
            </li>
          ))}
        </ul>
      </section>

      <section className="ui-section">
        <h2>Радиусы и тени</h2>
        <ul className="ui-samples">
          {radii.map((name) => (
            <li key={name} className="ui-sample" style={{ borderRadius: `var(--radius-${name})` }}>
              <code>--radius-{name}</code>
            </li>
          ))}
        </ul>
        <ul className="ui-samples">
          {shadows.map((level) => (
            <li
              key={level}
              className="ui-sample ui-sample--raised"
              style={{ boxShadow: `var(--shadow-${level})`, borderRadius: "var(--radius-md)" }}
            >
              <code>--shadow-{level}</code>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
