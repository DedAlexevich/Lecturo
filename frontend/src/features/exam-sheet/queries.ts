import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
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

function detailOf(body: unknown): unknown {
  return typeof body === "object" && body !== null && "detail" in body ? body.detail : undefined;
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
    refetchInterval: (query) => (errorCode(query.state.error) === "exam_sheet_processing" ? pollInterval : false),
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
