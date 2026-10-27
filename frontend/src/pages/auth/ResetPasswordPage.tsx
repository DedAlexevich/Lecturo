import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Button } from "../../ui/Button";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { useToast } from "../../ui/Toast";
import { AuthLayout } from "./AuthLayout";
import { fieldErrorsOf, messageOf, type FieldErrors } from "./errors";
import { useConfirmPasswordReset, useRequestPasswordReset } from "./useAuthRequests";
import { validateEmail, validateNewPassword, validatePasswordConfirm } from "./validation";

function RequestReset() {
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string>();
  const request = useRequestPasswordReset();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const emailError = validateEmail(email);
    setErrors({ email: emailError });
    setFormError(undefined);
    if (emailError) return;

    request.mutate(email.trim(), {
      onError: (error) => {
        const fields = fieldErrorsOf(error);
        setErrors(fields);
        if (Object.values(fields).length === 0) setFormError(messageOf(error));
      },
    });
  }

  if (request.isSuccess) {
    return (
      <AuthLayout
        title="Проверьте почту"
        lead="Если аккаунт с таким адресом есть, мы отправили на него ссылку для нового пароля."
        footer={<Link to="/login">Вернуться ко входу</Link>}
      />
    );
  }

  return (
    <AuthLayout
      title="Сброс пароля"
      lead="Укажите почту, и мы пришлём ссылку для нового пароля."
      footer={<Link to="/login">Вернуться ко входу</Link>}
    >
      <form className="auth__form" onSubmit={handleSubmit} noValidate>
        {formError && (
          <p className="auth__alert" role="alert">
            {formError}
          </p>
        )}
        <Field label="Почта" error={errors.email}>
          {(control) => (
            <Input
              {...control}
              type="email"
              name="email"
              autoComplete="email"
              inputMode="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          )}
        </Field>
        <Button type="submit" fullWidth loading={request.isPending}>
          Отправить ссылку
        </Button>
      </form>
    </AuthLayout>
  );
}

function ConfirmReset({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string>();
  const confirm = useConfirmPasswordReset();
  const navigate = useNavigate();
  const toast = useToast();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const passwordError = validateNewPassword(password);
    const repeatError = validatePasswordConfirm(password, repeat);
    setErrors({ password: passwordError, password_repeat: repeatError });
    setFormError(undefined);
    if (passwordError || repeatError) return;

    confirm.mutate(
      { token, password },
      {
        onSuccess: () => {
          toast.show("Пароль изменён, теперь можно войти", "success");
          navigate("/login", { replace: true });
        },
        onError: (error) => {
          const fields = fieldErrorsOf(error);
          setErrors(fields);
          if (Object.values(fields).length === 0) setFormError(messageOf(error));
        },
      },
    );
  }

  return (
    <AuthLayout title="Новый пароль" lead="Придумайте пароль, которым будете входить дальше.">
      <form className="auth__form" onSubmit={handleSubmit} noValidate>
        {formError && (
          <p className="auth__alert" role="alert">
            {formError}
          </p>
        )}
        <Field label="Новый пароль" hint="От 8 символов" error={errors.password}>
          {(control) => (
            <Input
              {...control}
              type="password"
              name="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        <Field label="Повторите новый пароль" error={errors.password_repeat}>
          {(control) => (
            <Input
              {...control}
              type="password"
              name="password_repeat"
              autoComplete="new-password"
              value={repeat}
              onChange={(event) => {
                setRepeat(event.target.value);
                setErrors((current) => ({ ...current, password_repeat: undefined }));
              }}
            />
          )}
        </Field>
        <Button type="submit" fullWidth loading={confirm.isPending}>
          Сохранить пароль
        </Button>
      </form>
    </AuthLayout>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  return token ? <ConfirmReset token={token} /> : <RequestReset />;
}
