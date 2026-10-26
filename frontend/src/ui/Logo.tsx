import "./Logo.css";

export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <span className={`logo logo--${size}`} aria-label="Lecturo">
      Lectur<span className="logo__mark">o</span>
    </span>
  );
}
