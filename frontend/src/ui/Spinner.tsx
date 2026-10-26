import "./Spinner.css";

export function Spinner({ size = "md", label = "Загрузка" }: { size?: "sm" | "md" | "lg"; label?: string }) {
  return (
    <span className={`spinner spinner--${size}`} role="status" aria-label={label}>
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle className="spinner__track" cx="12" cy="12" r="9" />
        <circle className="spinner__arc" cx="12" cy="12" r="9" />
      </svg>
    </span>
  );
}
