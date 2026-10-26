import "./Logo.css";

export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <span className={`logo logo--${size}`} aria-label="Lecturo">
      <svg className="logo__mark" viewBox="0 0 16 16" aria-hidden="true">
        <rect x="0" y="2" width="16" height="3" rx="1.5" />
        <rect x="0" y="6.5" width="10" height="3" rx="1.5" className="logo__accent" />
        <rect x="0" y="11" width="13" height="3" rx="1.5" />
      </svg>
      Lecturo
    </span>
  );
}
