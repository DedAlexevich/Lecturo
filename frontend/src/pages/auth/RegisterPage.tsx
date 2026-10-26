import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Button } from "../../ui/Button";
import { Checkbox } from "../../ui/Checkbox";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { AuthLayout } from "./AuthLayout";
import { SocialLogin } from "./SocialLogin";
import { fieldErrorsOf, messageOf, type FieldErrors } from "./errors";
import { redirectTarget } from "./redirect";
import { useRegister } from "./useAuthRequests";
import { validateEmail, validateNewPassword } from "./validation";

export function RegisterPage() {
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string>();
  const register = useRegister();
  const navigate = useNavigate();
  const location = useLocation();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next: FieldErrors = {
      email: validateEmail(email),
      password: validateNewPassword(password),
      accept_terms: accepted ? undefined : "Без согласия мы не можем создать аккаунт",
    };
    setErrors(next);
    setFormError(undefined);
    if (next.email || next.password || next.accept_terms) return;

    register.mutate(
      { email: email.trim(), password, display_name: displayName.trim(), accept_terms: accepted },
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
      title="Регистрация"
      lead="Бесплатный тариф включает несколько лекций в месяц."
      footer={
        <>
          Уже есть аккаунт? <Link to="/login" state={location.state}>Войти</Link>
        </>
      }
    >
      <form className="auth__form" onSubmit={handleSubmit} noValidate>
        {formError && (
          <p className="auth__alert" role="alert">
            {formError}
          </p>
        )}
        <Field label="Как к вам обращаться" hint="Необязательно">
          {(control) => (
            <Input
              {...control}
              name="name"
              autoComplete="name"
              maxLength={120}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          )}
        </Field>
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
        <Field label="Пароль" hint="От 8 символов" error={errors.password}>
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
        <div>
          <Checkbox
            checked={accepted}
            invalid={Boolean(errors.accept_terms)}
            onChange={(event) => setAccepted(event.target.checked)}
            label={
              <>
                Принимаю <Link to="/legal/terms" target="_blank">пользовательское соглашение</Link>,{" "}
                <Link to="/legal/privacy" target="_blank">политику обработки данных</Link> и{" "}
                <Link to="/legal/personal-data-consent" target="_blank">согласие на обработку персональных данных</Link>
              </>
            }
          />
          {errors.accept_terms && (
            <p className="field__error" role="alert">
              {errors.accept_terms}
            </p>
          )}
        </div>
        <Button type="submit" fullWidth loading={register.isPending}>
          Создать аккаунт
        </Button>
      </form>
      <SocialLogin />
    </AuthLayout>
  );
}
