import { useCallback, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { useToast } from "../../ui/Toast";
import { ConsentFields } from "./ConsentFields";
import { TelegramButton, telegramEnabled } from "./TelegramButton";
import { messageOf } from "./errors";
import { redirectTarget } from "./redirect";
import { useTelegramLogin, type TelegramUser } from "./useAuthRequests";

type Consents = { accept_terms: boolean; accept_personal_data: boolean };

export function SocialLogin() {
  const login = useTelegramLogin();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [pending, setPending] = useState<TelegramUser>();
  const [terms, setTerms] = useState(false);
  const [personalData, setPersonalData] = useState(false);
  const { mutate } = login;

  const submit = useCallback(
    (user: TelegramUser, consents: Consents) =>
      mutate(
        { ...user, ...consents },
        {
          onSuccess: () => navigate(redirectTarget(location.state), { replace: true }),
          onError: (error) => {
            if (error instanceof ApiError && error.status === 403) {
              setPending(user);
              return;
            }
            setPending(undefined);
            toast.show(messageOf(error), "error");
          },
        },
      ),
    [mutate, navigate, location.state, toast],
  );

  const handleAuth = useCallback(
    (user: TelegramUser) => submit(user, { accept_terms: false, accept_personal_data: false }),
    [submit],
  );

  function closeDialog() {
    setPending(undefined);
    setTerms(false);
    setPersonalData(false);
  }

  if (!telegramEnabled) return null;

  return (
    <>
      <div className="auth__divider">или</div>
      <TelegramButton onAuth={handleAuth} />
      <Dialog
        open={pending !== undefined}
        onClose={closeDialog}
        title="Создание аккаунта"
        actions={
          <>
            <Button variant="ghost" onClick={closeDialog}>
              Отмена
            </Button>
            <Button
              disabled={!terms || !personalData}
              loading={login.isPending}
              onClick={() => pending && submit(pending, { accept_terms: terms, accept_personal_data: personalData })}
            >
              Продолжить
            </Button>
          </>
        }
      >
        <p>Чтобы войти через Telegram впервые, примите документы.</p>
        <ConsentFields
          terms={terms}
          personalData={personalData}
          onTermsChange={setTerms}
          onPersonalDataChange={setPersonalData}
        />
      </Dialog>
    </>
  );
}
