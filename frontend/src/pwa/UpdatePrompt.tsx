import { useSyncExternalStore } from "react";
import { Button } from "../ui/Button";
import { applyServiceWorkerUpdate, dismissUpdate, getUpdateState, subscribeUpdate } from "./register";
import "./UpdatePrompt.css";

export function UpdatePrompt() {
  const { needRefresh } = useSyncExternalStore(subscribeUpdate, getUpdateState, getUpdateState);

  if (!needRefresh) return null;

  return (
    <div className="update-prompt" role="status">
      <span className="update-prompt__message">Доступна новая версия</span>
      <Button size="sm" onClick={applyServiceWorkerUpdate}>
        Обновить
      </Button>
      <button type="button" className="update-prompt__close" aria-label="Закрыть уведомление" onClick={dismissUpdate}>
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>
  );
}
