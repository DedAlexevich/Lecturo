import { useState } from "react";
import { Button } from "./Button";
import { Checkbox } from "./Checkbox";
import { Dialog } from "./Dialog";
import { EmptyState } from "./EmptyState";
import { Field } from "./Field";
import { Input } from "./Input";
import { Logo } from "./Logo";
import { Progress } from "./Progress";
import { Spinner } from "./Spinner";
import { Tabs } from "./Tabs";
import { ThemeToggle } from "./ThemeToggle";
import { useToast } from "./Toast";
import "./UiPage.css";

const colorGroups: { title: string; tokens: string[] }[] = [
  { title: "Фон и поверхности", tokens: ["bg", "surface", "surface-sunken", "border", "border-strong"] },
  { title: "Текст", tokens: ["text", "text-muted"] },
  { title: "Акцент", tokens: ["accent", "accent-hover", "accent-soft", "on-accent", "data", "data-soft"] },
  { title: "Состояния", tokens: ["success", "warning", "danger"] },
];

const textSizes = [
  { token: "3xl", sample: "Конспект лекции" },
  { token: "2xl", sample: "Основы термодинамики" },
  { token: "xl", sample: "Второе начало и энтропия" },
  { token: "lg", sample: "Энтропия замкнутой системы не убывает" },
  { token: "base", sample: "Преподаватель разбирает цикл Карно и объясняет, почему КПД не может быть равен единице." },
  { token: "sm", sample: "Загружено 12 октября, длительность 1 ч 24 мин" },
  { token: "xs", sample: "Таймкод 00:42:17" },
];

const spaces = [1, 2, 3, 4, 5, 6, 7, 8];
const radii = ["sm", "md", "lg", "pill"];
const shadows = [2, 3];

export function UiPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const toast = useToast();

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
        <p className="ui-note">Весь интерфейс набран одним шрифтом Inter, иерархию задают размер и насыщенность.</p>
        <ul className="ui-type">
          {textSizes.map((item) => (
            <li key={item.token} className="ui-type__row">
              <code>--text-{item.token}</code>
              <span style={{ fontSize: `var(--text-${item.token})` }}>
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

      <section className="ui-section">
        <h2>Кнопки</h2>
        <div className="ui-row">
          <Button>Загрузить лекцию</Button>
          <Button variant="secondary">Отмена</Button>
          <Button variant="ghost">Подробнее</Button>
          <Button variant="danger">Удалить</Button>
        </div>
        <div className="ui-row">
          <Button size="sm">Скачать</Button>
          <Button size="sm" variant="secondary">
            Поделиться
          </Button>
          <Button loading>Обработка</Button>
          <Button disabled>Недоступно</Button>
          <Button variant="secondary" disabled>
            Недоступно
          </Button>
        </div>
        <Button fullWidth>Во всю ширину</Button>
      </section>

      <section className="ui-section">
        <h2>Поля и флажки</h2>
        <div className="ui-form">
          <Field label="Название лекции" hint="Показывается в списке конспектов">
            {(control) => <Input placeholder="Термодинамика, лекция 4" {...control} />}
          </Field>
          <Field label="Почта" error="Не похоже на адрес почты">
            {(control) => <Input defaultValue="student@" {...control} />}
          </Field>
          <Field label="Группа">{(control) => <Input value="ИВТ-21" disabled readOnly {...control} />}</Field>
          <Checkbox label="Отправить конспект на почту" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} />
          <Checkbox label="Только для чтения" checked disabled readOnly />
          <Checkbox label="Нужно принять условия" invalid />
        </div>
      </section>

      <section className="ui-section">
        <h2>Вкладки</h2>
        <Tabs
          label="Разделы конспекта"
          items={[
            { id: "summary", label: "Конспект", panel: <p>Краткое изложение лекции по разделам.</p> },
            { id: "transcript", label: "Расшифровка", panel: <p>Полный текст с таймкодами.</p> },
            { id: "cards", label: "Карточки", panel: <p>Вопросы для повторения перед экзаменом.</p> },
          ]}
        />
      </section>

      <section className="ui-section">
        <h2>Прогресс и загрузка</h2>
        <div className="ui-form">
          <Progress label="Распознавание речи" value={64} />
          <Progress label="Подготовка конспекта" />
        </div>
        <div className="ui-row">
          <Spinner size="sm" />
          <Spinner />
          <Spinner size="lg" />
        </div>
      </section>

      <section className="ui-section">
        <h2>Диалог и уведомления</h2>
        <div className="ui-row">
          <Button variant="secondary" onClick={() => setDialogOpen(true)}>
            Открыть диалог
          </Button>
          <Button variant="secondary" onClick={() => toast.show("Лекция добавлена в очередь")}>
            Уведомление
          </Button>
          <Button variant="secondary" onClick={() => toast.show("Конспект готов", "success")}>
            Успех
          </Button>
          <Button variant="secondary" onClick={() => toast.show("Не удалось загрузить файл", "error")}>
            Ошибка
          </Button>
        </div>
        <Dialog
          open={dialogOpen}
          onClose={() => setDialogOpen(false)}
          title="Удалить лекцию?"
          actions={
            <>
              <Button variant="secondary" onClick={() => setDialogOpen(false)}>
                Отмена
              </Button>
              <Button variant="danger" onClick={() => setDialogOpen(false)}>
                Удалить
              </Button>
            </>
          }
        >
          Конспект и расшифровка будут удалены без возможности восстановления.
        </Dialog>
      </section>

      <section className="ui-section">
        <h2>Пустое состояние</h2>
        <EmptyState
          title="Лекций пока нет"
          description="Загрузите запись, и через несколько минут здесь появится конспект."
          action={<Button>Загрузить лекцию</Button>}
        />
      </section>
    </main>
  );
}
