import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { signOut } from "../../app/session";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Spinner } from "../../ui/Spinner";
import { useToast } from "../../ui/Toast";
import { settingsError, useDeleteAccount, useLinkTelegram } from "../account/settings";
import { AuthLayout } from "./AuthLayout";
import { ConsentFields } from "./ConsentFields";
import { messageOf } from "./errors";
import { isTelegramMode, parseTelegramUser, type TelegramMode, type TelegramUser } from "./telegramParams";
import { useTelegramLogin } from "./useAuthRequests";

const titles: Record<TelegramMode, string> = {
  login: "Вход через Telegram",
  link: "Привязка Telegram",
  delete: "Удаление аккаунта",
};

const retryTargets: Record<TelegramMode, string> = {
  login: "/login",
  link: "/account",
  delete: "/account",
};

const invalidMessage = "Telegram не передал данные для входа. Попробуйте ещё раз";

export function TelegramCallbackPage() {
  const { mode: modeParam } = useParams();
  const mode: TelegramMode = isTelegramMode(modeParam) ? modeParam : "login";
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const login = useTelegramLogin();
  const link = useLinkTelegram();
  const remove = useDeleteAccount();
  const [user, setUser] = useState<TelegramUser>();
  const [needsConsents, setNeedsConsents] = useState(false);
  const [terms, setTerms] = useState(false);
  const [personalData, setPersonalData] = useState(false);
  const [failure, setFailure] = useState<string>();
  const started = useRef(false);
  const { mutate: signIn } = login;
  const { mutate: linkTelegram } = link;
  const { mutate: deleteAccount } = remove;

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const parsed = parseTelegramUser(params);
    if (!parsed) {
      setFailure(invalidMessage);
      return;
    }
    setUser(parsed);
    if (mode === "link") {
      linkTelegram(parsed, {
        onSuccess: () => {
          toast.show("Telegram привязан", "success");
          navigate("/account", { replace: true });
        },
        onError: (error) => setFailure(settingsError(error)),
      });
      return;
    }
    if (mode === "delete") {
      deleteAccount(
        { telegram: parsed },
        {
          onSuccess: () => {
            toast.show("Аккаунт удалён", "success");
            signOut();
            navigate("/login", { replace: true });
          },
          onError: (error) => setFailure(settingsError(error, "Подтверждение не прошло")),
        },
      );
      return;
    }
    signIn(
      { ...parsed, accept_terms: false, accept_personal_data: false },
      {
        onSuccess: () => navigate("/", { replace: true }),
        onError: (error) => {
          if (error instanceof ApiError && error.status === 403) {
            setNeedsConsents(true);
            return;
          }
          setFailure(messageOf(error));
        },
      },
    );
  }, [params, mode, signIn, linkTelegram, deleteAccount, navigate, toast]);

  const leave = () => navigate("/login", { replace: true });

  const accept = () => {
    if (!user) return;
    signIn(
      { ...user, accept_terms: terms, accept_personal_data: personalData },
      {
        onSuccess: () => navigate("/", { replace: true }),
        onError: (error) => {
          setNeedsConsents(false);
          setFailure(messageOf(error));
        },
      },
    );
  };

  return (
    <AuthLayout title={titles[mode]} lead={failure ? undefined : "Проверяем данные, это займёт несколько секунд."}>
      {failure ? (
        <>
          <p className="auth__alert" role="alert">
            {failure}
          </p>
          <p className="auth__footer">
            <Link to={retryTargets[mode]}>Попробовать снова</Link>
          </p>
        </>
      ) : (
        <Spinner label="Проверяем данные Telegram" />
      )}
      <Dialog
        open={needsConsents}
        onClose={leave}
        title="Создание аккаунта"
        actions={
          <>
            <Button variant="ghost" onClick={leave}>
              Отмена
            </Button>
            <Button disabled={!terms || !personalData} loading={login.isPending} onClick={accept}>
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
    </AuthLayout>
  );
}
