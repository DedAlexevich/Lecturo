import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { detailOf } from "../../api/errors";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type ExamSheet = components["schemas"]["ExamSheetOut"];

export type Definition = {
  term: string;
  definition: string;
};

const pollInterval = 4000;

export function examSheetQueryKey(courseId: string) {
  return ["exam-sheet", courseId];
}

export function errorCode(error: Error | null) {
  if (!(error instanceof ApiError)) return null;
  const detail = detailOf(error.body);
  if (typeof detail === "object" && detail !== null && "code" in detail && typeof detail.code === "string") {
    return detail.code;
  }
  return null;
}

export function errorMessage(error: Error | null) {
  if (!(error instanceof ApiError)) return null;
  const detail = detailOf(error.body);
  return typeof detail === "string" ? detail : null;
}

export function createErrorText(error: Error | null) {
  const code = errorCode(error);
  if (code === "no_summaries") {
    return "В курсе пока нет лекций с готовым конспектом. Памятку можно собрать, когда обработается хотя бы одна лекция.";
  }
  if (code === "subscription_required") return "Памятка доступна только с подпиской.";
  if (error instanceof ApiError && error.status === 503) return "Очередь сейчас недоступна. Попробуйте через пару минут.";
  return errorMessage(error) ?? "Не получилось запустить сборку памятки. Попробуйте ещё раз.";
}

export function definitionsOf(sheet: ExamSheet): Definition[] {
  return sheet.definitions.flatMap(({ term, definition }) =>
    term && definition ? [{ term, definition }] : [],
  );
}

export function useExamSheet(courseId: string) {
  return useQuery({
    queryKey: examSheetQueryKey(courseId),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/courses/{course_id}/exam-sheet", {
        params: { path: { course_id: courseId } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    refetchInterval: (query) =>
      query.state.data?.processing || errorCode(query.state.error) === "exam_sheet_processing" ? pollInterval : false,
  });
}

export function useCreateExamSheet(courseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error, response } = await api.POST("/api/v1/courses/{course_id}/exam-sheet", {
        params: { path: { course_id: courseId } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: examSheetQueryKey(courseId) }),
  });
}
