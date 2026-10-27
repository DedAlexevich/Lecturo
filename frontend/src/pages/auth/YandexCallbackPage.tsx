import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Spinner } from "../../ui/Spinner";
import { useToast } from "../../ui/Toast";
import { useLinkYandex } from "../account/settings";
import { AuthLayout } from "./AuthLayout";
import { ConsentFields } from "./ConsentFields";
import { messageOf } from "./errors";
import { takeYandexFlow, useYandexLogin, useYandexStart, type YandexFlow } from "./yandex";

const loginFlow: YandexFlow = { mode: "login", redirect: "/" };

export function YandexCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const login = useYandexLogin();
  const link = useLinkYandex();
  const [flow, setFlow] = useState<YandexFlow>(loginFlow);
  const [needsConsents, setNeedsConsents] = useState(false);
  const [terms, setTerms] = useState(false);
  const [personalData, setPersonalData] = useState(false);
  const [failure, setFailure] = useState<string>();
  const restart = useYandexStart(flow);
  const started = useRef(false);
  const { mutate: signInWithYandex } = login;
  const { mutate: linkYandex } = link;

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const stored = takeYandexFlow();
    const code = params.get("code");
    const state = params.get("state");
    if (!stored || !code || !state) {
      setFailure("Не удалось завершить вход через Яндекс. Попробуйте ещё раз");
      return;
    }
    setFlow(stored);
    const body = { code, state, nonce: stored.nonce };
    if (stored.mode === "link") {
      linkYandex(body, {
        onSuccess: () => {
          toast.show("Яндекс привязан", "success");
          navigate("/account", { replace: true });
        },
        onError: (error) => {
          toast.show(messageOf(error), "error");
          navigate("/account", { replace: true });
        },
      });
      return;
    }
    signInWithYandex(body, {
      onSuccess: () => navigate(stored.redirect, { replace: true }),
      onError: (error) => {
        if (error instanceof ApiError && error.status === 403) {
          setNeedsConsents(true);
          return;
        }
        setFailure(messageOf(error));
      },
    });
  }, [params, linkYandex, signInWithYandex, navigate, toast]);

  const leave = () => navigate("/login", { replace: true });

  return (
    <AuthLayout title="Вход через Яндекс" lead={failure ? undefined : "Проверяем данные, это займёт несколько секунд."}>
      {failure ? (
        <>
          <p className="auth__alert" role="alert">
            {failure}
          </p>
          <p className="auth__footer">
            <Link to="/login">Вернуться ко входу</Link>
          </p>
        </>
      ) : (
        <Spinner label="Входим через Яндекс" />
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
            <Button
              disabled={!terms || !personalData}
              loading={restart.isPending || restart.isSuccess}
              onClick={() =>
                restart.mutate(
                  { accept_terms: terms, accept_personal_data: personalData },
                  {
                    onError: (error) => {
                      setNeedsConsents(false);
                      setFailure(messageOf(error));
                    },
                  },
                )
              }
            >
              Продолжить
            </Button>
          </>
        }
      >
        <p>Чтобы войти через Яндекс впервые, примите документы.</p>
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
