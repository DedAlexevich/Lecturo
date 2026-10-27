import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Spinner } from "../../ui/Spinner";
import { useToast } from "../../ui/Toast";
import { useLinkVk } from "../account/settings";
import { AuthLayout } from "./AuthLayout";
import { ConsentFields } from "./ConsentFields";
import { messageOf } from "./errors";
import { takeVkFlow, useVkLogin, useVkStart, type VkFlow } from "./vk";

const loginFlow: VkFlow = { mode: "login", redirect: "/" };

export function VkCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const login = useVkLogin();
  const link = useLinkVk();
  const [flow, setFlow] = useState<VkFlow>(loginFlow);
  const [needsConsents, setNeedsConsents] = useState(false);
  const [terms, setTerms] = useState(false);
  const [personalData, setPersonalData] = useState(false);
  const [failure, setFailure] = useState<string>();
  const restart = useVkStart(flow);
  const started = useRef(false);
  const { mutate: signInWithVk } = login;
  const { mutate: linkVk } = link;

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const stored = takeVkFlow();
    const code = params.get("code");
    const state = params.get("state");
    const deviceId = params.get("device_id");
    if (!stored || !code || !state || !deviceId) {
      setFailure("Не удалось завершить вход через VK. Попробуйте ещё раз");
      return;
    }
    setFlow(stored);
    const body = { code, state, device_id: deviceId, nonce: stored.nonce };
    if (stored.mode === "link") {
      linkVk(body, {
        onSuccess: () => {
          toast.show("VK привязан", "success");
          navigate("/account", { replace: true });
        },
        onError: (error) => {
          toast.show(messageOf(error), "error");
          navigate("/account", { replace: true });
        },
      });
      return;
    }
    signInWithVk(body, {
      onSuccess: () => navigate(stored.redirect, { replace: true }),
      onError: (error) => {
        if (error instanceof ApiError && error.status === 403) {
          setNeedsConsents(true);
          return;
        }
        setFailure(messageOf(error));
      },
    });
  }, [params, linkVk, signInWithVk, navigate, toast]);

  const leave = () => navigate("/login", { replace: true });

  return (
    <AuthLayout title="Вход через VK" lead={failure ? undefined : "Проверяем данные, это займёт несколько секунд."}>
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
        <Spinner label="Входим через VK" />
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
        <p>Чтобы войти через VK впервые, примите документы.</p>
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
