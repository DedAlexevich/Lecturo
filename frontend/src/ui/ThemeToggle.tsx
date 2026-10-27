import { getWebApp } from "../telegram/sdk";
import { useTheme, type ThemeChoice } from "./theme";
import "./ThemeToggle.css";

const options: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Авто" },
  { value: "light", label: "Светлая" },
  { value: "dark", label: "Тёмная" },
];

export function ThemeToggle() {
  const { choice, select } = useTheme();
  if (getWebApp()) return null;

  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Тема оформления">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={choice === option.value}
          className="theme-toggle__option"
          onClick={() => select(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
