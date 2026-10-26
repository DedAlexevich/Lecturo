import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
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

export function useAiTransferConsent() {
  const { data: me } = useMe();
  const accept = useAcceptAiTransfer();
  const { reset } = accept;
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState(false);
  const pending = useRef<(() => void) | null>(null);

  const close = useCallback(() => {
    pending.current = null;
    setOpen(false);
    setChecked(false);
    reset();
  }, [reset]);

  const requireConsent = useCallback(
    (action: () => void) => {
      if (!me) return;
      if (me.ai_transfer_accepted_at) {
        action();
        return;
      }
      pending.current = action;
      setOpen(true);
    },
    [me],
  );

  const confirm = () => {
    accept.mutate(undefined, {
      onSuccess: () => {
        const action = pending.current;
        close();
        action?.();
      },
    });
  };

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

  return { requireConsent, dialog };
}
