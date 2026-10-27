import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { queryClient } from "../../app/queryClient";
import { useToken } from "../../app/session";
import { Button } from "../../ui/Button";
import { useToast } from "../../ui/Toast";
import { rememberIntent, takeIntent } from "./copyIntent";
import { copyShared } from "./copyRequests";

type SaveCopyButtonProps = {
  token: string;
  lectureId: string | null;
  course?: boolean;
  note: string;
};

function failureMessage(status: number, message: string | null, course: boolean) {
  if (status === 404) return "Ссылка больше не работает, сохранить не получилось.";
  if (status === 429) return message ?? "Слишком много запросов, попробуйте позже.";
  if (status === 403) return message ?? "Сохранять лекции могут только подтверждённые аккаунты.";
  if (status === 401) return "Войдите, чтобы сохранить.";
  return course ? "Не удалось сохранить курс. Попробуйте ещё раз." : "Не удалось сохранить лекцию. Попробуйте ещё раз.";
}

export function SaveCopyButton({ token, lectureId, course = false, note }: SaveCopyButtonProps) {
  const session = useToken();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const running = useRef(false);

  const run = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    try {
      const result = await copyShared(token, lectureId);
      if (result.kind === "failed") {
        toast.show(failureMessage(result.status, result.message, course), "error");
        return;
      }
      const target = result.courseId !== null ? `/courses/${result.courseId}` : result.lectureId !== null ? `/lectures/${result.lectureId}` : null;
      if (result.kind === "own") {
        toast.show(course ? "Это ваш курс, открываем его." : "Это ваша лекция, открываем её.", "info");
      } else if (result.created) {
        toast.show(course ? "Курс сохранён в ваш кабинет." : "Лекция сохранена в ваш кабинет.", "success");
        void queryClient.invalidateQueries();
      } else {
        toast.show(course ? "Этот курс уже сохранён у вас." : "Эта лекция уже сохранена у вас.", "info");
      }
      if (target !== null) navigate(target);
    } catch {
      toast.show("Не удалось сохранить. Проверьте соединение.", "error");
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [token, lectureId, course, navigate, toast]);

  useEffect(() => {
    if (session !== null && takeIntent({ token, lectureId })) void run();
  }, [session, token, lectureId, run]);

  const click = () => {
    if (session === null) {
      rememberIntent({ token, lectureId });
      navigate("/login", { state: { from: location } });
      return;
    }
    void run();
  };

  return (
    <div className="public__save">
      <Button loading={busy} onClick={click}>
        {course ? "Сохранить курс себе" : "Сохранить себе"}
      </Button>
      <p className="public__save-note">{session === null ? `${note} Для сохранения нужно войти или создать аккаунт.` : note}</p>
    </div>
  );
}
