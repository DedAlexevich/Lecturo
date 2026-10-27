import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { formatDate } from "../../pages/legal/formatDate";
import { Button } from "../../ui/Button";
import "./LegalUpdateNotice.css";

type LegalUpdate = components["schemas"]["LegalUpdateOut"];

const revocable = new Set(["ai-transfer"]);

function storageKey(update: LegalUpdate) {
  return `lecturo.legal-update.${update.slug}.${update.revision_date}`;
}

function wasDismissed(update: LegalUpdate) {
  try {
    return localStorage.getItem(storageKey(update)) !== null;
  } catch {
    return false;
  }
}

function localToday() {
  return new Date().toLocaleDateString("sv-SE");
}

export function LegalUpdateNotice() {
  const [dismissed, setDismissed] = useState<string[]>([]);
  const { data: updates = [] } = useQuery({
    queryKey: ["legal", "updates"],
    staleTime: 60 * 60 * 1000,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/legal/updates");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });

  const update = updates.find((item) => !dismissed.includes(storageKey(item)) && !wasDismissed(item));
  if (!update) return null;

  function dismiss(item: LegalUpdate) {
    setDismissed((keys) => [...keys, storageKey(item)]);
    try {
      localStorage.setItem(storageKey(item), new Date().toISOString());
    } catch {
      return;
    }
  }

  const effective = formatDate(update.effective_date);
  const inForce = update.effective_date <= localToday();

  return (
    <aside className="legal-update" aria-label="Новая редакция документа">
      <div className="legal-update__text">
        <p>
          <strong>
            Новая редакция: <Link to={`/legal/${update.slug}`}>{update.title}</Link>
          </strong>
          {inForce ? `, действует с ${effective}.` : `, вступает в силу ${effective}.`}
        </p>
        {update.changes && <p>{update.changes}</p>}
        {!inForce && (
          <p className="legal-update__note">
            С этой даты она действует без отдельного подтверждения. Если вы не согласны, до этой даты{" "}
            {revocable.has(update.slug) ? "отзовите согласие или удалите аккаунт в " : "удалите аккаунт в "}
            <Link to="/account">кабинете</Link>.
          </p>
        )}
      </div>
      <Button variant="ghost" size="sm" onClick={() => dismiss(update)}>
        Понятно
      </Button>
    </aside>
  );
}
