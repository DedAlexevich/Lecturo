import { detailOf } from "../../api/errors";
import { ApiError } from "../../app/queryClient";

export type FieldErrors = Partial<Record<string, string>>;

type ValidationDetail = { loc: (string | number)[]; msg: string };

const fieldMessages: Record<string, Record<string, string>> = {
  email: { default: "Проверьте адрес почты" },
  password: { default: "Пароль должен быть от 8 до 128 символов" },
  accept_terms: { default: "Нужно принять пользовательское соглашение" },
  accept_personal_data: { default: "Нужно дать согласие на обработку персональных данных" },
};

export function fieldErrorsOf(error: unknown): FieldErrors {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  const detail = detailOf(error.body);
  if (!Array.isArray(detail)) return {};
  const result: FieldErrors = {};
  for (const item of detail as ValidationDetail[]) {
    const field = String(item.loc[item.loc.length - 1]);
    if (field in fieldMessages) result[field] = fieldMessages[field].default;
  }
  return result;
}

export function messageOf(error: unknown): string {
  if (!(error instanceof ApiError)) return "Не удалось связаться с сервером. Проверьте интернет и попробуйте ещё раз";
  const detail = detailOf(error.body);
  switch (error.status) {
    case 401:
    case 403:
    case 409:
      return typeof detail === "string" ? detail : "Не получилось, попробуйте ещё раз";
    case 503:
      return typeof detail === "string" ? detail : "Сервис временно недоступен, попробуйте позже";
    case 400:
    case 410:
      return typeof detail === "string" ? detail : "Ссылка устарела или уже использована";
    case 422:
      return "Проверьте введённые данные";
    case 429:
      return typeof detail === "string" ? detail : "Слишком много попыток. Подождите немного и повторите";
    case 501:
      return "Эта возможность скоро заработает";
    default:
      return "Что-то пошло не так. Попробуйте ещё раз чуть позже";
  }
}
