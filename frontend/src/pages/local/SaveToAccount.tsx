import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router";
import { tokenStorage } from "../../api/client";
import { useToken } from "../../app/session";
import { useMe } from "../../app/useMe";
import { useAiTransferConsent } from "../../features/consent/useAiTransferConsent";
import { markLocalLectureSynced } from "../../local/storage";
import type { LocalLecture } from "../../local/storage";
import { saveToAccount, syncError } from "../../local/sync/save";
import { Button } from "../../ui/Button";

export function SaveToAccount({ lecture }: { lecture: LocalLecture }) {
  const token = useToken();
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { requireConsent, dialog } = useAiTransferConsent();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<{ userId: string; lectureId: string } | null>(null);
  const locked = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const userId = me.data?.id;
  const existingId = userId && (created?.userId === userId ? created.lectureId : lecture.syncedLectures?.[userId]);

  async function save() {
    if (!userId || locked.current) return;
    locked.current = true;
    setPending(true);
    setError("");
    try {
      const result = await saveToAccount(lecture);
      setCreated({ userId, lectureId: result.id });
      await markLocalLectureSynced(lecture.id, userId, result.id).catch(() => {});
      void queryClient.invalidateQueries({ queryKey: ["lectures"] });
      if (mounted.current && tokenStorage.get() === token) navigate(`/lectures/${result.id}`);
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
      ) : existingId ? (
        <Link to={`/lectures/${existingId}`}>Открыть лекцию в аккаунте</Link>
      ) : (
        <Button variant="secondary" loading={pending} disabled={!me.data} onClick={() => requireConsent(() => void save())}>Сохранить в аккаунт</Button>
      )}
      {token !== null && me.isError && <p className="local-error" role="alert">Не удалось проверить аккаунт. Обновите страницу и попробуйте снова.</p>}
      {error && <p className="local-error" role="alert">{error}</p>}
      {dialog}
    </div>
  );
}
