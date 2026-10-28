import { ApiError } from "../../app/queryClient";
import { detailOf } from "../../api/errors";

export function linkErrorOf(error: unknown) {
  if (!(error instanceof ApiError)) return "Не удалось связаться с сервером. Проверьте интернет и попробуйте ещё раз";
  const detail = detailOf(error.body);
  if (typeof detail === "string") return detail;
  if (error.status === 422) return "Проверьте ссылку";
  return "Не получилось добавить лекцию. Попробуйте ещё раз";
}
