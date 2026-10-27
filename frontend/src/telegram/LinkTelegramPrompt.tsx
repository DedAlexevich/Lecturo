import { useState } from "react";
import { useMe } from "../app/useMe";
import { getMiniAppInitData } from "../pages/account/miniApp";
import { settingsError, useLinkTelegram } from "../pages/account/settings";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { useToast } from "../ui/Toast";

const dismissedKey = "lecturo:telegram-link-dismissed";

function wasDismissed() {
  try {
    return sessionStorage.getItem(dismissedKey) === "1";
  } catch {
    return false;
  }
}

function rememberDismissed() {
  try {
    sessionStorage.setItem(dismissedKey, "1");
  } catch {
    return;
  }
}

export function LinkTelegramPrompt() {
  const me = useMe();
  const link = useLinkTelegram();
  const toast = useToast();
  const [dismissed, setDismissed] = useState(wasDismissed);
  const initData = getMiniAppInitData();
  const needsLink = me.data !== undefined && !me.data.identities.some((identity) => identity.provider === "telegram");

  if (!initData) return null;

  const close = () => {
    rememberDismissed();
    setDismissed(true);
    link.reset();
  };

  const confirm = () =>
    link.mutate(
      { telegram_init_data: initData },
      {
        onSuccess: () => {
          toast.show("Telegram привязан", "success");
          close();
        },
      },
    );

  return (
    <Dialog
      open={needsLink && !dismissed}
      onClose={close}
      title="Привязать этот Telegram?"
      actions={
        <>
          <Button variant="ghost" disabled={link.isPending} onClick={close}>
            Не сейчас
          </Button>
          <Button loading={link.isPending} onClick={confirm}>
            Привязать
          </Button>
        </>
      }
    >
      <p>Так вы сможете входить в этот аккаунт из Telegram без пароля.</p>
      {link.isError && <p role="alert">{settingsError(link.error)}</p>}
    </Dialog>
  );
}
