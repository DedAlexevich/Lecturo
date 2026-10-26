import type { ReactNode } from "react";
import "./auth.css";

type AuthLayoutProps = {
  title: string;
  lead?: string;
  children?: ReactNode;
  footer?: ReactNode;
};

export function AuthLayout({ title, lead, children, footer }: AuthLayoutProps) {
  return (
    <section className="auth">
      <h1 className="auth__title">{title}</h1>
      {lead && <p className="auth__lead">{lead}</p>}
      {children}
      {footer && <p className="auth__footer">{footer}</p>}
    </section>
  );
}
