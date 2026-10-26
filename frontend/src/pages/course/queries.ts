import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";

export type CourseFields = {
  title: string;
  description: string;
};

export function courseQueryKey(courseId: string) {
  return ["courses", courseId];
}

export function useCourse(courseId: string) {
  return useQuery({
    queryKey: courseQueryKey(courseId),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/courses/{course_id}", {
        params: { path: { course_id: courseId } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useCreateCourse() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CourseFields) => {
      const { data, error, response } = await api.POST("/api/v1/courses", { body });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["courses"], exact: true }),
  });
}

export function useUpdateCourse(courseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CourseFields) => {
      const { data, error, response } = await api.PATCH("/api/v1/courses/{course_id}", {
        params: { path: { course_id: courseId } },
        body,
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (course) => {
      queryClient.setQueryData(courseQueryKey(courseId), course);
      return queryClient.invalidateQueries({ queryKey: ["courses"], exact: true });
    },
  });
}

export function useDeleteCourse(courseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error, response } = await api.DELETE("/api/v1/courses/{course_id}", {
        params: { path: { course_id: courseId } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["courses"], exact: true }),
  });
}

function useRefreshCourse(courseId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: courseQueryKey(courseId) }),
      queryClient.invalidateQueries({ queryKey: ["courses"], exact: true }),
    ]);
}

export function useAddLectures(courseId: string) {
  const refresh = useRefreshCourse(courseId);
  return useMutation({
    mutationFn: async (lectureIds: string[]) => {
      for (const lectureId of lectureIds) {
        const { error, response } = await api.POST("/api/v1/courses/{course_id}/lectures", {
          params: { path: { course_id: courseId } },
          body: { lecture_id: lectureId },
        });
        if (!response.ok) throw new ApiError(response.status, error);
      }
    },
    onSettled: refresh,
  });
}

export function useRemoveLecture(courseId: string) {
  const refresh = useRefreshCourse(courseId);
  return useMutation({
    mutationFn: async (lectureId: string) => {
      const { error, response } = await api.DELETE("/api/v1/courses/{course_id}/lectures/{lecture_id}", {
        params: { path: { course_id: courseId, lecture_id: lectureId } },
      });
      if (response.ok) return;
      if (response.status === 404) {
        const course = await api.GET("/api/v1/courses/{course_id}", { params: { path: { course_id: courseId } } });
        if (course.data !== undefined) return;
      }
      throw new ApiError(response.status, error);
    },
    onSettled: refresh,
  });
}
