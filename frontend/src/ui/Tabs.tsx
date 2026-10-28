import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import "./Tabs.css";

export type TabItem = {
  id: string;
  label: string;
  panel: ReactNode;
};

type TabsProps = {
  items: TabItem[];
  label: string;
  value?: string;
  onChange?: (id: string) => void;
};

export function Tabs({ items, label, value, onChange }: TabsProps) {
  const [inner, setInner] = useState(items[0]?.id);
  const current = value ?? inner;
  const baseId = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const select = (id: string) => {
    setInner(id);
    onChange?.(id);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = items.findIndex((item) => item.id === current);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % items.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    else return;
    event.preventDefault();
    select(items[next].id);
    refs.current[items[next].id]?.focus();
  };

  const active = items.find((item) => item.id === current);

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
        {items.map((item) => (
          <button
            key={item.id}
            ref={(node) => {
              refs.current[item.id] = node;
            }}
            type="button"
            role="tab"
            id={`${baseId}-tab-${item.id}`}
            aria-selected={item.id === current}
            aria-controls={item.id === current ? `${baseId}-panel-${item.id}` : undefined}
            tabIndex={item.id === current ? 0 : -1}
            className="tabs__tab"
            onClick={() => select(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {active && (
        <div
          className="tabs__panel"
          role="tabpanel"
          id={`${baseId}-panel-${active.id}`}
          aria-labelledby={`${baseId}-tab-${active.id}`}
          tabIndex={0}
        >
          {active.panel}
        </div>
      )}
    </div>
  );
}
