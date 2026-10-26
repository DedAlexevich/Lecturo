import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router";
import { TelegramButton, telegramEnabled } from "./TelegramButton";
import { messageOf } from "./errors";
import { useTelegramLogin } from "./useAuthRequests";
import { useToast } from "../../ui/Toast";
import { redirectTarget } from "./redirect";

export function SocialLogin() {
  const login = useTelegramLogin();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { mutate } = login;

  const handleAuth = useCallback(
    (user: Parameters<typeof mutate>[0]) =>
      mutate(user, {
        onSuccess: () => navigate(redirectTarget(location.state), { replace: true }),
        onError: (error) => toast.show(messageOf(error), "error"),
      }),
    [mutate, navigate, location.state, toast],
  );

  if (!telegramEnabled) return null;

  return (
    <>
      <div className="auth__divider">или</div>
      <TelegramButton onAuth={handleAuth} />
    </>
  );
}
