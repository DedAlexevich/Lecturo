import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Button } from "../../ui/Button";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { AuthLayout } from "./AuthLayout";
import { SocialLogin } from "./SocialLogin";
import { fieldErrorsOf, messageOf, type FieldErrors } from "./errors";
import { redirectTarget } from "./redirect";
import { useLogin } from "./useAuthRequests";
import { validateEmail } from "./validation";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string>();
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next: FieldErrors = {
      email: validateEmail(email),
      password: password === "" ? "Введите пароль" : undefined,
    };
    setErrors(next);
    setFormError(undefined);
    if (next.email || next.password) return;

    login.mutate(
      { email: email.trim(), password },
      {
        onSuccess: () => navigate(redirectTarget(location.state), { replace: true }),
        onError: (error) => {
          const fields = fieldErrorsOf(error);
          setErrors(fields);
          if (Object.keys(fields).length === 0) setFormError(messageOf(error));
        },
      },
    );
  }

  return (
    <AuthLayout
      title="Вход"
      lead="Лекции, конспекты и курсы ждут вас на месте."
      footer={
        <>
          Впервые здесь? <Link to="/register" state={location.state}>Создать аккаунт</Link>
        </>
      }
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
        <Field label="Пароль" error={errors.password}>
          {(control) => (
            <Input
              {...control}
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        <div className="auth__row">
          <Link to="/reset-password">Забыли пароль?</Link>
        </div>
        <Button type="submit" fullWidth loading={login.isPending}>
          Войти
        </Button>
      </form>
      <SocialLogin />
    </AuthLayout>
  );
}
