import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import "./Checkbox.css";

type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "children"> & {
  label: ReactNode;
  invalid?: boolean;
};

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, invalid, className, ...rest },
  ref,
) {
  return (
    <label className={className ? `checkbox ${className}` : "checkbox"}>
      <input ref={ref} type="checkbox" className="checkbox__input" aria-invalid={invalid || undefined} {...rest} />
      <span className="checkbox__box" aria-hidden="true">
        <svg viewBox="0 0 16 16" focusable="false">
          <path d="M3.5 8.5l3 3 6-6.5" />
        </svg>
      </span>
      <span className="checkbox__label">{label}</span>
    </label>
  );
});
