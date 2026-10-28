import type { ReactNode } from "react";
import "./EmptyState.css";

type EmptyStateProps = {
  title: string;
  description?: string;
  action?: ReactNode;
  level?: 1 | 2 | 3;
};

export function EmptyState({ title, description, action, level = 3 }: EmptyStateProps) {
  const Heading = `h${level}` as const;
  return (
    <div className="empty-state">
      <Heading className="empty-state__title">{title}</Heading>
      {description && <p className="empty-state__description">{description}</p>}
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}
