import type { ButtonHTMLAttributes } from "react";
import { Spinner } from "../../ui/Spinner";
import "../../ui/Button.css";
import "./ProviderButton.css";

export type LoginProvider = "telegram" | "vk" | "yandex";

type ProviderButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "type"> & {
  provider: LoginProvider;
  label: string;
  size?: "md" | "sm";
  fullWidth?: boolean;
  loading?: boolean;
};

export function ProviderButton({
  provider,
  label,
  size = "md",
  fullWidth = false,
  loading = false,
  disabled,
  className,
  ...rest
}: ProviderButtonProps) {
  const classes = ["button", "button--secondary", `button--${size}`, "provider-button"];
  if (fullWidth) classes.push("button--full", "provider-button--full");
  if (loading) classes.push("button--loading");
  if (className) classes.push(className);

  return (
    <button
      type="button"
      className={classes.join(" ")}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      <span className="provider-button__label">{label}</span>
      <span className="provider-button__mark">
        {loading ? <Spinner size="sm" label="Выполняется" /> : <ProviderLogo provider={provider} />}
      </span>
    </button>
  );
}

function ProviderLogo({ provider }: { provider: LoginProvider }) {
  if (provider === "telegram") {
    return (
      <svg className="provider-logo" viewBox="0 0 240 240" aria-hidden="true" focusable="false">
        <circle cx="120" cy="120" r="120" fill="#2aabee" />
        <path
          fill="#ffffff"
          d="M54.3 118.8c35-15.2 58.3-25.3 70-30.2 33.3-13.9 40.3-16.3 44.8-16.4 1 0 3.2.2 4.7 1.4 1.2 1 1.5 2.3 1.7 3.3s.4 3.1.2 4.7c-1.8 19-9.6 65.1-13.6 86.3-1.7 9-5 12-8.2 12.3-7 .6-12.3-4.6-19-9-10.6-6.9-16.5-11.2-26.8-18-11.9-7.8-4.2-12.1 2.6-19.1 1.8-1.8 32.5-29.8 33.1-32.3.1-.3.1-1.5-.6-2.1-.7-.6-1.7-.4-2.5-.2-1.1.2-17.9 11.4-50.6 33.5-4.8 3.3-9.1 4.9-13 4.8-4.3-.1-12.5-2.4-18.7-4.4-7.5-2.4-13.5-3.7-13-7.9.3-2.2 3.3-4.4 8.9-6.7z"
        />
      </svg>
    );
  }
  if (provider === "vk") {
    return (
      <svg className="provider-logo" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <rect x="1" y="1" width="22" height="22" rx="7" fill="#0077ff" />
        <path
          fill="#ffffff"
          d="M12.6 16.9c-4.8 0-7.5-3.3-7.6-8.8h2.4c.1 4 1.9 5.7 3.3 6.1V8.1h2.3v3.5c1.4-.2 2.8-1.7 3.3-3.5h2.3c-.4 2.1-1.9 3.7-3.1 4.4 1.2.5 2.9 1.9 3.6 4.4h-2.5c-.5-1.7-1.9-3-3.6-3.1v3.1z"
        />
      </svg>
    );
  }
  return (
    <svg className="provider-logo" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="12" fill="#fc3f1d" />
      <path
        fill="#ffffff"
        transform="translate(1.2 0)"
        d="M13.7 19.2V6.6h-1.4c-2.6 0-4 1.3-4 3.2 0 2.2.9 3.2 2.9 4.5l1.6 1.1-4.6 3.8H5.5l4.1-3.5C7.3 14.1 6 12.4 6 9.8 6 6.6 8.2 4.8 12.3 4.8H16v14.4z"
      />
    </svg>
  );
}
