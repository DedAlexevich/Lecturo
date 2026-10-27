import { useLocation } from "react-router";
import { useToast } from "../../ui/Toast";
import { TelegramButton, telegramEnabled } from "./TelegramButton";
import { VkButton } from "./VkButton";
import { messageOf } from "./errors";
import { redirectTarget } from "./redirect";
import { useVkEnabled } from "./vk";

export function SocialLogin() {
  const toast = useToast();
  const location = useLocation();
  const vkEnabled = useVkEnabled();

  if (!telegramEnabled && !vkEnabled) return null;

  return (
    <>
      <div className="auth__divider">или</div>
      <div className="auth-social">
        {telegramEnabled && <TelegramButton mode="login" />}
        {vkEnabled && (
          <VkButton
            flow={{ mode: "login", redirect: redirectTarget(location.state) }}
            label="Войти через VK"
            fullWidth
            onError={(error) => toast.show(messageOf(error), "error")}
          />
        )}
      </div>
    </>
  );
}
