import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { api } from "../api/client";
import { ApiError } from "../app/queryClient";
import { signIn, useToken, wasSignedOutByUser } from "../app/session";
import { ConsentFields } from "../pages/auth/ConsentFields";
import { messageOf } from "../pages/auth/errors";
import { ProviderButton } from "../pages/auth/ProviderButton";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { bindTheme, getWebApp } from "./sdk";
import "./TelegramBridge.css";

let automaticLoginDone = false;
let automaticLogin: ReturnType<typeof authenticate> | undefined;

async function authenticate(acceptTerms = false, acceptPersonalData = false) {
  const result = await api.POST("/api/v1/auth/telegram-webapp", {
    body: { init_data: getWebApp()?.initData ?? "", accept_terms: acceptTerms, accept_personal_data: acceptPersonalData },
  });
  if (!result.data) throw new ApiError(result.response.status, result.error);
  return result.data;
}

export function TelegramBridge() {
  const token = useToken();
  const location = useLocation();
  const navigate = useNavigate();
  const [consent, setConsent] = useState(false);
  const [terms, setTerms] = useState(false);
  const [personalData, setPersonalData] = useState(false);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [declined, setDeclined] = useState(false);

  useEffect(() => {
    const app = getWebApp();
    if (!app) return;
    const cleanup = bindTheme(app);
    app.ready();
    app.expand();
    return cleanup;
  }, []);

  useEffect(() => {
    const app = getWebApp();
    if (!app) return;
    const back = () => navigate(-1);
    if ((window.history.state?.idx ?? 0) > 0) app.BackButton.show();
    else app.BackButton.hide();
    app.BackButton.onClick(back);
    return () => {
      app.BackButton.offClick(back);
      app.BackButton.hide();
    };
  }, [location.key, navigate]);

  useEffect(() => {
    if (!getWebApp() || token !== null || automaticLoginDone || wasSignedOutByUser()) return;
    let active = true;
    automaticLogin ??= authenticate();
    automaticLogin.then(
      (tokens) => {
        if (active) {
          automaticLoginDone = true;
          signIn(tokens.access_token);
        }
      },
      (failure: unknown) => {
        if (!active) return;
        if (failure instanceof ApiError && failure.status === 403) setConsent(true);
        else setError(messageOf(failure));
      },
    );
    return () => {
      active = false;
    };
  }, [token]);

  if (!getWebApp()) return null;

  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const tokens = await authenticate(terms, personalData);
      automaticLogin = Promise.resolve(tokens);
      automaticLoginDone = true;
      signIn(tokens.access_token);
      setConsent(false);
      setDeclined(false);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 403) setConsent(true);
      else setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const decline = () => {
    if (busy) return;
    setConsent(false);
    setDeclined(true);
  };

  return (
    <>
      {!consent && (error || (token === null && (declined || wasSignedOutByUser()))) && (
        <div className="telegram-login">
          {error && <p role="alert" className="telegram-login__error">Вход через Telegram: {error}</p>}
          <ProviderButton
            provider="telegram"
            label={error ? "Повторить вход" : "Войти через Telegram"}
            fullWidth
            loading={busy}
            onClick={submit}
          />
        </div>
      )}
      <Dialog
        open={consent}
        onClose={decline}
        title="Создание аккаунта"
        actions={
          <>
            <Button variant="ghost" disabled={busy} onClick={decline}>Отмена</Button>
            <Button disabled={!terms || !personalData} loading={busy} onClick={submit}>Продолжить</Button>
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
        {error && <p role="alert">{error}</p>}
      </Dialog>
    </>
  );
}
