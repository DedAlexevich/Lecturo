import { useState, type MouseEvent } from "react";
import type { components } from "../../api/schema";
import { useMe } from "../../app/useMe";
import { LinkTelegram } from "../../pages/account/IdentitiesList";
import { getMiniAppInitData } from "../../pages/account/miniApp";
import { telegramBotUrl } from "../../telegram/bot";
import { getWebApp } from "../../telegram/sdk";
import { Button } from "../../ui/Button";
import "./TelegramNotice.css";

export type NoticeSubject = "lecture" | "regenerate" | "quiz";

const readyWhen: Record<NoticeSubject, string> = {
  lecture: "когда лекция будет готова",
  regenerate: "когда главы и конспект будут готовы",
  quiz: "когда квиз будет готов",
};

type TelegramState = components["schemas"]["TelegramNotifications"];

function offerAvailable(state: TelegramState) {
  if (state === "ready") return false;
  if (state === "not_linked") return Boolean(getMiniAppInitData()) || telegramBotUrl !== null;
  return telegramBotUrl !== null;
}

export function afterStartNote(state: TelegramState | undefined) {
  if (state === "ready") return " Можно закрыть страницу, пришлём уведомление в Telegram, когда лекция будет готова.";
  if (state && offerAvailable(state)) return " Уведомление в Telegram можно включить на странице лекции.";
  return "";
}

function storageKey(lectureId: string) {
  return `lecturo.telegram-offer-dismissed.${lectureId}`;
}

function wasDismissed(lectureId: string) {
  try {
    return localStorage.getItem(storageKey(lectureId)) !== null;
  } catch {
    return false;
  }
}

function rememberDismissed(lectureId: string) {
  try {
    localStorage.setItem(storageKey(lectureId), new Date().toISOString());
    return true;
  } catch {
    return false;
  }
}

function openBot(event: MouseEvent<HTMLAnchorElement>) {
  const app = getWebApp();
  if (!app?.openTelegramLink || !telegramBotUrl) return;
  event.preventDefault();
  app.openTelegramLink(telegramBotUrl);
}

export function TelegramNotice({ lectureId, subject }: { lectureId: string; subject: NoticeSubject }) {
  const { data: me } = useMe({ refetchOnWindowFocus: true });
  const [dismissedId, setDismissedId] = useState<string | null>(null);

  if (!me) return null;
  const state = me.telegram_notifications;

  if (state === "ready") {
    return (
      <p className="telegram-notice" role="status">
        Можно закрыть страницу, пришлём уведомление в Telegram, {readyWhen[subject]}.
      </p>
    );
  }

  if (dismissedId === lectureId || wasDismissed(lectureId) || !offerAvailable(state)) return null;

  const dismiss = () => {
    setDismissedId(lectureId);
    rememberDismissed(lectureId);
  };

  const text =
    state === "not_linked"
      ? `Привяжите Telegram, и мы пришлём уведомление, ${readyWhen[subject]}. Тогда страницу можно будет закрыть.`
      : state === "blocked"
        ? "Бот остановлен, откройте его и нажмите Start, чтобы получать уведомления."
        : `Можно закрыть страницу и получить уведомление в Telegram, ${readyWhen[subject]}. Для этого откройте бота и нажмите Start.`;

  return (
    <aside className="telegram-notice telegram-notice--offer" aria-label="Уведомление в Telegram">
      <p>{text}</p>
      <div className="telegram-notice__actions">
        {state === "not_linked" ? (
          <LinkTelegram />
        ) : (
          <a
            className="button button--secondary button--sm"
            href={telegramBotUrl ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            onClick={openBot}
          >
            Открыть бота
          </a>
        )}
        <Button variant="ghost" size="sm" onClick={dismiss}>
          Не нужно
        </Button>
      </div>
    </aside>
  );
}
