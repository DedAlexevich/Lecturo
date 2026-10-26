import { queryOptions, useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type Lecture = components["schemas"]["LectureOut"];
export type LectureStatus = components["schemas"]["LectureStatus"];
export type LectureProgress = components["schemas"]["LectureStatusOut"];
export type Course = components["schemas"]["CourseOut"];

const pollInterval = 4000;

const activeStatuses: LectureStatus[] = ["queued", "waiting_quota", "processing"];

export function isActive(status: LectureStatus) {
  return activeStatuses.includes(status);
}

function pollWhileActive(lectures: Lecture[] | undefined) {
  return lectures?.some((lecture) => isActive(lecture.status)) ? pollInterval : false;
}

export function useLectures(courseId: string | null) {
  return useQuery({
    queryKey: courseId ? ["courses", courseId, "lectures"] : ["lectures"],
    refetchInterval: (query) => pollWhileActive(query.state.data),
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

export function useProgress(lectures: Lecture[]) {
  const active = lectures.filter((lecture) => isActive(lecture.status));
  const results = useQueries({
    queries: active.map((lecture) =>
      queryOptions({
        queryKey: ["lectures", lecture.id, "status"],
        retry: false,
        refetchInterval: (query) => (query.state.status === "error" ? false : pollInterval),
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
  results.forEach((result, index) => {
    if (result.data) progress.set(active[index].id, result.data);
  });
  return progress;
}
