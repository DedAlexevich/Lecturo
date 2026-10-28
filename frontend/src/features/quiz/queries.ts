import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { api } from "../../api/client";
import { detailOf } from "../../api/errors";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { lectureQueryKey } from "../../pages/lecture/useLecture";

export type Quiz = components["schemas"]["QuizOut"];
export type QuizQuestion = components["schemas"]["QuizQuestion"];
type Step = components["schemas"]["StepOut"];

const POLL_INTERVAL_MS = 3000;

function quizQueryKey(id: string) {
  return ["quiz", id] as const;
}

function quizStatusQueryKey(id: string) {
  return ["quiz-status", id] as const;
}

export function quizStepOf(steps: Step[] | undefined) {
  return steps?.find((step) => step.step === "quiz") ?? null;
}

export function isBuilding(step: Step | null) {
  return step !== null && (step.status === "pending" || step.status === "running");
}

export function needsSubscription(error: unknown) {
  if (!(error instanceof ApiError) || error.status !== 403) return false;
  const detail = detailOf(error.body);
  return typeof detail === "object" && detail !== null && "code" in detail && detail.code === "subscription_required";
}

export function quizErrorOf(error: unknown) {
  if (!(error instanceof ApiError)) return "Не удалось связаться с сервером. Проверьте интернет и попробуйте ещё раз.";
  const detail = detailOf(error.body);
  if (typeof detail === "string") return detail;
  return "Не получилось запустить квиз. Попробуйте ещё раз.";
}

export function useQuiz(id: string, enabled: boolean) {
  return useQuery({
    queryKey: quizQueryKey(id),
    enabled,
    queryFn: async (): Promise<Quiz | null> => {
      const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}/quiz", {
        params: { path: { lecture_id: id } },
      });
      if (response.status === 404) return null;
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useQuizStep(id: string, enabled: boolean) {
  return useQuery({
    queryKey: quizStatusQueryKey(id),
    enabled,
    refetchInterval: (current) => (isBuilding(current.state.data ?? null) ? POLL_INTERVAL_MS : false),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}/status", {
        params: { path: { lecture_id: id } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return quizStepOf(data.steps);
    },
  });
}

export function useRefreshQuiz(id: string) {
  const queryClient = useQueryClient();
  return useCallback(
    () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: quizQueryKey(id) }),
        queryClient.invalidateQueries({ queryKey: lectureQueryKey(id), exact: true }),
      ]),
    [queryClient, id],
  );
}

export function useCreateQuiz(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error, response } = await api.POST("/api/v1/lectures/{lecture_id}/quiz", {
        params: { path: { lecture_id: id } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => {
      const pending: Step = { step: "quiz", status: "pending", progress: 0, error: null };
      queryClient.setQueryData(quizStatusQueryKey(id), pending);
      return queryClient.invalidateQueries({ queryKey: quizStatusQueryKey(id) });
    },
  });
}
