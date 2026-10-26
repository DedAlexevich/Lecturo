import "./Progress.css";

type ProgressProps = {
  label: string;
  value?: number;
  showValue?: boolean;
};

export function Progress({ label, value, showValue = true }: ProgressProps) {
  const determinate = typeof value === "number";
  const percent = determinate ? Math.min(100, Math.max(0, Math.round(value))) : undefined;

  return (
    <div className="progress">
      <div className="progress__head">
        <span className="progress__label">{label}</span>
        {showValue && determinate && <span className="progress__value">{percent}%</span>}
      </div>
      <div
        className={determinate ? "progress__track" : "progress__track progress__track--indeterminate"}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div className="progress__bar" style={determinate ? { width: `${percent}%` } : undefined} />
      </div>
    </div>
  );
}
