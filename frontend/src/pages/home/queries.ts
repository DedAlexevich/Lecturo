import { queryOptions, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { lectureStatusQueryKey } from "../lecture/useLecture";

export type Lecture = components["schemas"]["LectureOut"];
export type LectureStatus = components["schemas"]["LectureStatus"];
export type LectureProgress = components["schemas"]["LectureStatusOut"];
export type Course = components["schemas"]["CourseOut"];

const pollInterval = 4000;

const activeStatuses: LectureStatus[] = ["queued", "waiting_quota", "processing"];

export function isActive(status: LectureStatus) {
  return activeStatuses.includes(status);
}

export function useLectures(courseId: string | null) {
  return useQuery({
    queryKey: courseId ? ["courses", courseId, "lectures"] : ["lectures"],
    queryFn: async () => {
      if (courseId) {
        const { data, error, response } = await api.GET("/api/v1/courses/{course_id}/lectures", {
          params: { path: { course_id: courseId } },
        });
        if (data === undefined) throw new ApiError(response.status, error);
        return data;
      }
      const { data, error, response } = await api.GET("/api/v1/lectures");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useCourses() {
  return useQuery({
    queryKey: ["courses"],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/courses");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

function isUnavailable(error: Error | null) {
  return error instanceof ApiError && (error.status === 501 || (error.status >= 400 && error.status < 500));
}

export function useProgress(lectures: Lecture[]) {
  const queryClient = useQueryClient();
  const active = lectures.filter((lecture) => isActive(lecture.status));
  const results = useQueries({
    queries: active.map((lecture) =>
      queryOptions({
        queryKey: lectureStatusQueryKey(lecture.id),
        retry: false,
        refetchInterval: (query) => {
          if (isUnavailable(query.state.error)) return false;
          const polled = query.state.data;
          return polled && !isActive(polled.status) ? false : pollInterval;
        },
        queryFn: async () => {
          const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}/status", {
            params: { path: { lecture_id: lecture.id } },
          });
          if (data === undefined) throw new ApiError(response.status, error);
          return data;
        },
      }),
    ),
  });

  const progress = new Map<string, LectureProgress>();
  const changed: string[] = [];
  results.forEach((result, index) => {
    const lecture = active[index];
    if (!result.data) return;
    progress.set(lecture.id, result.data);
    if (result.data.status !== lecture.status) changed.push(`${lecture.id}:${result.data.status}`);
  });

  const changes = changed.join(",");
  const requested = useRef("");
  useEffect(() => {
    if (changes === "" || changes === requested.current) return;
    requested.current = changes;
    void queryClient.invalidateQueries({ queryKey: ["lectures"], exact: true });
    void queryClient.invalidateQueries({
      predicate: (query) => query.queryKey[0] === "courses" && query.queryKey[2] === "lectures",
    });
  }, [changes, queryClient]);

  return progress;
}
