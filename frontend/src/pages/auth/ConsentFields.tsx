import { Link } from "react-router";
import { Checkbox } from "../../ui/Checkbox";
import type { FieldErrors } from "./errors";

type ConsentFieldsProps = {
  terms: boolean;
  personalData: boolean;
  onTermsChange: (value: boolean) => void;
  onPersonalDataChange: (value: boolean) => void;
  errors?: FieldErrors;
};

export function ConsentFields({ terms, personalData, onTermsChange, onPersonalDataChange, errors = {} }: ConsentFieldsProps) {
  return (
    <div className="auth__consents">
      <div>
        <Checkbox
          checked={terms}
          invalid={Boolean(errors.accept_terms)}
          onChange={(event) => onTermsChange(event.target.checked)}
          label={
            <>
              Принимаю <Link to="/legal/terms" target="_blank" rel="noopener noreferrer">пользовательское соглашение</Link> и{" "}
              <Link to="/legal/privacy" target="_blank" rel="noopener noreferrer">политику обработки данных</Link>
            </>
          }
        />
        {errors.accept_terms && (
          <p className="field__error" role="alert">
            {errors.accept_terms}
          </p>
        )}
      </div>
      <div>
        <Checkbox
          checked={personalData}
          invalid={Boolean(errors.accept_personal_data)}
          onChange={(event) => onPersonalDataChange(event.target.checked)}
          label={
            <>
              Даю <Link to="/legal/personal-data-consent" target="_blank" rel="noopener noreferrer">согласие на обработку персональных данных</Link>
            </>
          }
        />
        {errors.accept_personal_data && (
          <p className="field__error" role="alert">
            {errors.accept_personal_data}
          </p>
        )}
      </div>
    </div>
  );
}
