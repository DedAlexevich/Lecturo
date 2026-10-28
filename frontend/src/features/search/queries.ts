import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type SearchScope = { lectureId: string } | { courseId: string } | { all: true };
export type SearchHit = components["schemas"]["SearchHit"];

export const MIN_QUERY_LENGTH = 2;

export function searchErrorText(error: Error | null) {
  if (error instanceof ApiError && error.status === 429) {
    return "Слишком много поисковых запросов. Подождите минуту и попробуйте ещё раз.";
  }
  return "Поиск не сработал. Проверьте соединение и попробуйте ещё раз.";
}

export function useDebouncedValue<T>(value: T, delay: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function useSearch(scope: SearchScope, query: string) {
  const q = query.trim();
  const params =
    "lectureId" in scope
      ? { lecture_id: scope.lectureId }
      : "courseId" in scope
        ? { course_id: scope.courseId }
        : {};
  return useQuery({
    queryKey: ["search", params, q],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/search", {
        params: { query: { q, ...params } },
        signal,
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    enabled: q.length >= MIN_QUERY_LENGTH,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}
