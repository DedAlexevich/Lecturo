import { ApiError } from "../../app/queryClient";

export function detailOf(body: unknown): unknown {
  return typeof body === "object" && body !== null && "detail" in body ? body.detail : undefined;
}

export function linkErrorOf(error: unknown) {
  if (!(error instanceof ApiError)) return "Не удалось связаться с сервером. Проверьте интернет и попробуйте ещё раз";
  const detail = detailOf(error.body);
  if (typeof detail === "string") return detail;
  if (error.status === 422) return "Проверьте ссылку";
  return "Не получилось добавить лекцию. Попробуйте ещё раз";
}
