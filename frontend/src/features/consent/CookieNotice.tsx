import { useState } from "react";
import { Link } from "react-router";
import { Button } from "../../ui/Button";
import "./CookieNotice.css";

const STORAGE_KEY = "lecturo.cookies-ack";

function wasAcknowledged() {
  try {
    return localStorage.getItem(STORAGE_KEY) !== null;
  } catch {
    return false;
  }
}

export function CookieNotice() {
  const [visible, setVisible] = useState(() => !wasAcknowledged());

  if (!visible) return null;

  function acknowledge() {
    setVisible(false);
    try {
      localStorage.setItem(STORAGE_KEY, new Date().toISOString());
    } catch {
      return;
    }
  }

  return (
    <aside className="cookie-notice" role="region" aria-label="Уведомление о cookie">
      <p className="cookie-notice__text">
        Мы используем cookie и локальное хранилище браузера, чтобы вы оставались в аккаунте и работала тема оформления.{" "}
        <Link to="/legal/cookies">Подробнее</Link>
      </p>
      <Button size="sm" onClick={acknowledge}>
        Понятно
      </Button>
    </aside>
  );
}
