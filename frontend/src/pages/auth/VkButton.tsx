import { ProviderButton } from "./ProviderButton";
import { useVkStart, type VkConsents, type VkFlow } from "./vk";

const noConsents: VkConsents = { accept_terms: false, accept_personal_data: false };

type VkButtonProps = {
  flow: VkFlow;
  label: string;
  ariaLabel?: string;
  size?: "sm" | "md";
  fullWidth?: boolean;
  onError: (error: unknown) => void;
};

export function VkButton({ flow, label, ariaLabel, size = "md", fullWidth = false, onError }: VkButtonProps) {
  const start = useVkStart(flow);
  return (
    <ProviderButton
      provider="vk"
      label={label}
      aria-label={ariaLabel}
      size={size}
      fullWidth={fullWidth}
      loading={start.isPending || start.isSuccess}
      onClick={() => start.mutate(noConsents, { onError })}
    />
  );
}
