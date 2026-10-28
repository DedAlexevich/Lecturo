import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";
import { meQueryKey, useMe } from "../../app/useMe";
import { Button } from "../../ui/Button";
import { Checkbox } from "../../ui/Checkbox";
import { Dialog } from "../../ui/Dialog";

function useAcceptAiTransfer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/v1/me/consents/ai-transfer");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (me) => queryClient.setQueryData(meQueryKey, me),
  });
}

type Me = NonNullable<ReturnType<typeof useMe>["data"]>;

export function useAiTransferConsent() {
  const { data: me, isError: meFailed, isFetching: meFetching, refetch: refetchMe } = useMe();
  const accept = useAcceptAiTransfer();
  const { reset } = accept;
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const pending = useRef<(() => void) | null>(null);

  const close = useCallback(() => {
    pending.current = null;
    setOpen(false);
    setWaiting(false);
    setChecked(false);
    reset();
  }, [reset]);

  const proceed = useCallback((user: Me) => {
    if (user.ai_transfer_accepted_at) {
      const action = pending.current;
      pending.current = null;
      setOpen(false);
      action?.();
      return;
    }
    setOpen(true);
  }, []);

  const requireConsent = useCallback(
    (action: () => void) => {
      pending.current = action;
      if (me) proceed(me);
      else if (meFailed) setOpen(true);
      else setWaiting(true);
    },
    [me, meFailed, proceed],
  );

  useEffect(() => {
    if (!waiting) return;
    if (me) {
      setWaiting(false);
      proceed(me);
    } else if (meFailed) {
      setWaiting(false);
      setOpen(true);
    }
  }, [waiting, me, meFailed, proceed]);

  const retryMe = async () => {
    const result = await refetchMe();
    if (result.data && pending.current) proceed(result.data);
  };

  const confirm = () => {
    accept.mutate(undefined, {
      onSuccess: () => {
        const action = pending.current;
        close();
        action?.();
      },
    });
  };

  if (open && !me) {
    return {
      requireConsent,
      waiting,
      dialog: (
        <Dialog
          open
          onClose={close}
          title="Передача данных провайдерам ИИ"
          actions={
            <>
              <Button variant="ghost" onClick={close}>
                Отмена
              </Button>
              <Button loading={meFetching} onClick={() => void retryMe()}>
                Повторить
              </Button>
            </>
          }
        >
          <p className="field__error" role="alert">
            Не удалось загрузить данные профиля. Проверьте соединение и попробуйте ещё раз.
          </p>
        </Dialog>
      ),
    };
  }

  const dialog = (
    <Dialog
      open={open}
      onClose={close}
      title="Передача данных провайдерам ИИ"
      actions={
        <>
          <Button variant="ghost" onClick={close}>
            Отмена
          </Button>
          <Button disabled={!checked} loading={accept.isPending} onClick={confirm}>
            Продолжить
          </Button>
        </>
      }
    >
      <p>
        Чтобы расшифровать и разобрать лекцию, мы передаём её запись и текст внешним провайдерам ИИ. Согласие нужно дать один раз.
      </p>
      <Checkbox
        checked={checked}
        onChange={(event) => setChecked(event.target.checked)}
        label={
          <>
            Согласен на <Link to="/legal/ai-transfer" target="_blank" rel="noopener noreferrer">передачу данных провайдерам ИИ</Link>
          </>
        }
      />
      {accept.isError && (
        <p className="field__error" role="alert">
          Не удалось сохранить согласие. Попробуйте ещё раз.
        </p>
      )}
    </Dialog>
  );

  return { requireConsent, waiting, dialog };
}
