import { Link } from "react-router";
import { Checkbox } from "../../ui/Checkbox";

type OfferConsentProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  error?: string;
};

export function OfferConsent({ checked, onChange, error }: OfferConsentProps) {
  return (
    <div>
      <Checkbox
        checked={checked}
        invalid={Boolean(error)}
        onChange={(event) => onChange(event.target.checked)}
        label={
          <>
            Принимаю <Link to="/legal/offer" target="_blank" rel="noopener noreferrer">публичную оферту</Link> и{" "}
            <Link to="/legal/refund" target="_blank" rel="noopener noreferrer">правила возврата</Link>
          </>
        }
      />
      {error && (
        <p className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
