import { Button } from "../../ui/Button";
import { useYandexStart, type YandexConsents, type YandexFlow } from "./yandex";

const noConsents: YandexConsents = { accept_terms: false, accept_personal_data: false };

type YandexButtonProps = {
  flow: YandexFlow;
  label: string;
  size?: "sm" | "md";
  fullWidth?: boolean;
  onError: (error: unknown) => void;
};

export function YandexButton({ flow, label, size = "md", fullWidth = false, onError }: YandexButtonProps) {
  const start = useYandexStart(flow);
  return (
    <Button
      variant="secondary"
      size={size}
      fullWidth={fullWidth}
      loading={start.isPending || start.isSuccess}
      onClick={() => start.mutate(noConsents, { onError })}
    >
      {label}
    </Button>
  );
}
