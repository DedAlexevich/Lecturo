import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Spinner } from "./Spinner";
import "./Button.css";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "md" | "sm";
  loading?: boolean;
  fullWidth?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, fullWidth = false, disabled, className, children, type = "button", ...rest },
  ref,
) {
  const classes = ["button", `button--${variant}`, `button--${size}`];
  if (fullWidth) classes.push("button--full");
  if (loading) classes.push("button--loading");
  if (className) classes.push(className);

  return (
    <button
      ref={ref}
      type={type}
      className={classes.join(" ")}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <Spinner size="sm" label="Выполняется" />}
      <span className="button__label">{children}</span>
    </button>
  );
});
