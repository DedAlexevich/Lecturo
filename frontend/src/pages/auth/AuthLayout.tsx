import type { ReactNode } from "react";
import "./auth.css";

type AuthLayoutProps = {
  title: string;
  lead?: string;
  children?: ReactNode;
  footer?: ReactNode;
};

const sampleLines = [
  { time: "0:00", text: "Сегодня разбираем второе начало термодинамики." },
  { time: "0:42", text: "Энтропия замкнутой системы не убывает.", current: true },
  { time: "1:24", text: "Вспомним цикл Карно и его коэффициент полезного действия." },
  { time: "2:06", text: "КПД не может быть равен единице при конечной температуре холодильника." },
];

export function AuthLayout({ title, lead, children, footer }: AuthLayoutProps) {
  return (
    <div className="auth-page">
      <section className="auth">
        <h1 className="auth__title">{title}</h1>
        {lead && <p className="auth__lead">{lead}</p>}
        {children}
        {footer && <p className="auth__footer">{footer}</p>}
      </section>
      <aside className="auth-sample" aria-hidden="true">
        <p className="auth-sample__title">Расшифровка лекции</p>
        <ul className="auth-sample__list">
          {sampleLines.map((line) => (
            <li key={line.time} className={line.current ? "auth-sample__line auth-sample__line--current" : "auth-sample__line"}>
              <span className="auth-sample__time">{line.time}</span>
              <span>{line.text}</span>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
