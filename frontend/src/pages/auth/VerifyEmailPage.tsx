import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router";
import { useToken } from "../../app/session";
import { Button } from "../../ui/Button";
import { Spinner } from "../../ui/Spinner";
import { useToast } from "../../ui/Toast";
import { AuthLayout } from "./AuthLayout";
import { messageOf } from "./errors";
import { useConfirmEmail, useRequestEmailVerification } from "./useAuthRequests";

function ConfirmEmail({ token }: { token: string }) {
  const { mutate, isSuccess, isError, error } = useConfirmEmail();

  const sentToken = useRef<string>();

  useEffect(() => {
    if (sentToken.current === token) return;
    sentToken.current = token;
    mutate(token);
  }, [mutate, token]);

  if (isSuccess) {
    return (
      <AuthLayout title="Почта подтверждена" lead="Спасибо, теперь адрес привязан к вашему аккаунту.">
        <div className="auth__actions">
          <Link to="/">
            <Button>Перейти к лекциям</Button>
          </Link>
        </div>
      </AuthLayout>
    );
  }

  if (isError) {
    return (
      <AuthLayout title="Не удалось подтвердить почту" lead={messageOf(error)}>
        <div className="auth__actions">
          <Link to="/account">
            <Button variant="secondary">Запросить новое письмо</Button>
          </Link>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Подтверждаем почту">
      <div className="auth__status">
        <Spinner label="Проверяем ссылку" />
        <span>Это займёт пару секунд</span>
      </div>
    </AuthLayout>
  );
}

function AwaitConfirmation() {
  const signedIn = useToken() !== null;
  const request = useRequestEmailVerification();
  const toast = useToast();

  function resend() {
    request.mutate(undefined, {
      onSuccess: () => toast.show("Письмо отправлено", "success"),
      onError: (error) => toast.show(messageOf(error), "error"),
    });
  }

  return (
    <AuthLayout
      title="Подтвердите почту"
      lead="Мы отправили письмо со ссылкой. Откройте её, и адрес будет подтверждён."
    >
      <div className="auth__actions">
        {signedIn ? (
          <Button variant="secondary" loading={request.isPending} onClick={resend}>
            Отправить письмо ещё раз
          </Button>
        ) : (
          <Link to="/login">
            <Button variant="secondary">Войти, чтобы запросить письмо</Button>
          </Link>
        )}
      </div>
    </AuthLayout>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  return token ? <ConfirmEmail token={token} /> : <AwaitConfirmation />;
}
