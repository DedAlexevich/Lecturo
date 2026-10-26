import { forwardRef, type InputHTMLAttributes } from "react";
import "./Input.css";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={className ? `input ${className}` : "input"} {...rest} />;
});
