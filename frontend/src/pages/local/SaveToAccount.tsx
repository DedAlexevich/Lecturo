import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router";
import { tokenStorage } from "../../api/client";
import { ApiError } from "../../app/queryClient";
import { useToken } from "../../app/session";
import { useMe } from "../../app/useMe";
import { useAiTransferConsent } from "../../features/consent/useAiTransferConsent";
import { markLocalLectureSynced } from "../../local/storage";
import type { LocalLecture } from "../../local/storage";
import { saveToAccount, syncError } from "../../local/sync/save";
import { Button } from "../../ui/Button";
import { fetchLecture } from "../lecture/useLecture";

export function SaveToAccount({ lecture }: { lecture: LocalLecture }) {
  const token = useToken();
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { requireConsent, dialog } = useAiTransferConsent();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [storageError, setStorageError] = useState(false);
  const [created, setCreated] = useState<{ userId: string; lectureId: string } | null>(null);
  const locked = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const userId = me.data?.id;
  const storageKey = userId ? `lecturo.local-sync.${userId}.${lecture.id}` : "";
  let fallbackId: string | null = null;
  try {
    fallbackId = storageKey ? localStorage.getItem(storageKey) : null;
  } catch {
    fallbackId = null;
  }
  const existingId = userId && (created?.userId === userId ? created.lectureId : fallbackId ?? lecture.syncedLectures?.[userId]);
  const existing = useQuery({
    queryKey: ["local-sync", existingId],
    queryFn: () => fetchLecture(existingId!),
    enabled: Boolean(existingId && token),
    retry: false,
  });
  const missing = existing.error instanceof ApiError && existing.error.status === 404;

  async function save() {
    if (!userId || locked.current) return;
    locked.current = true;
    setPending(true);
    setError("");
    try {
      const result = await saveToAccount(lecture);
      setCreated({ userId, lectureId: result.id });
      let linked = false;
      try {
        await markLocalLectureSynced(lecture.id, userId, result.id);
        linked = true;
        try { localStorage.removeItem(storageKey); } catch { setStorageError(true); }
      } catch {
        try {
          localStorage.setItem(storageKey, result.id);
          linked = true;
        } catch {
          setStorageError(true);
        }
      }
      queryClient.setQueryData(["local-sync", result.id], result);
      void queryClient.invalidateQueries({ queryKey: ["lectures"] });
      if (linked && mounted.current && tokenStorage.get() === token) navigate(`/lectures/${result.id}`);
    } catch (reason) {
      setError(syncError(reason));
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  return (
    <div className="local-sync">
      {token === null ? (
        <p className="local-note"><Link to="/login" state={{ from: location }}>Войдите в аккаунт</Link>, чтобы сохранить результат. После входа откройте его в списке на этом устройстве.</p>
      ) : existingId && !missing ? (
        existing.isError && !storageError ? (
          <p className="local-error" role="alert">Не удалось проверить сохранённую лекцию. <button type="button" onClick={() => void existing.refetch()}>Повторить</button></p>
        ) : <Link to={`/lectures/${existingId}`}>Открыть лекцию в аккаунте</Link>
      ) : (
        <Button variant="secondary" loading={pending} disabled={!me.data} onClick={() => requireConsent(() => void save())}>Сохранить в аккаунт</Button>
      )}
      {token !== null && me.isError && <p className="local-error" role="alert">Не удалось проверить аккаунт. Обновите страницу и попробуйте снова.</p>}
      {missing && <p className="local-note">Лекция удалена из аккаунта. Можно сохранить её снова.</p>}
      {storageError && <p className="local-error" role="alert">Лекция сохранена в аккаунте, но браузер не смог запомнить связь. Откройте лекцию по ссылке и сохраните её адрес: после перезагрузки повторная отправка создаст копию.</p>}
      {error && <p className="local-error" role="alert">{error}</p>}
      {dialog}
    </div>
  );
}
