import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";

type ReceiptEmailFieldProps = {
  value: string;
  onChange: (value: string) => void;
  error?: string;
};

export function ReceiptEmailField({ value, onChange, error }: ReceiptEmailFieldProps) {
  return (
    <Field label="Email для чека" hint="В аккаунте нет почты, чек об оплате пришлём сюда." error={error}>
      {(control) => (
        <Input
          {...control}
          type="email"
          inputMode="email"
          autoComplete="email"
          spellCheck={false}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  );
}
