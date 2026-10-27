import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";

export function useRenameLecture(lectureId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (title: string) => {
      const { data, error, response } = await api.PATCH("/api/v1/lectures/{lecture_id}", {
        params: { path: { lecture_id: lectureId } },
        body: { title },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["lectures"] }),
        client.invalidateQueries({ queryKey: ["courses"] }),
      ]);
    },
  });
}

export function useDeleteLecture(lectureId: string, onDeleted: () => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error, response } = await api.DELETE("/api/v1/lectures/{lecture_id}", {
        params: { path: { lecture_id: lectureId } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: async () => {
      await client.cancelQueries({ queryKey: ["lectures", lectureId] });
      onDeleted();
      await Promise.all([
        client.invalidateQueries({ queryKey: ["lectures"], exact: true }),
        client.invalidateQueries({ queryKey: ["courses"] }),
      ]);
      client.removeQueries({ queryKey: ["lectures", lectureId], type: "inactive" });
    },
  });
}

export function lectureCoursesKey(lectureId: string) {
  return ["lectures", lectureId, "courses"];
}

export function useLectureCourses(lectureId: string, enabled: boolean) {
  return useQuery({
    queryKey: lectureCoursesKey(lectureId),
    enabled,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/courses", {
        params: { query: { lecture_id: lectureId } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export type CourseChange = {
  add: string[];
  remove: string[];
  newCourse?: string;
};

export function useChangeLectureCourses(lectureId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ add, remove, newCourse }: CourseChange) => {
      const targets = [...add];
      if (newCourse) {
        const { data, error, response } = await api.POST("/api/v1/courses", {
          body: { title: newCourse, description: "" },
        });
        if (data === undefined) throw new ApiError(response.status, error);
        targets.push(data.id);
      }
      for (const courseId of targets) {
        const { error, response } = await api.POST("/api/v1/courses/{course_id}/lectures", {
          params: { path: { course_id: courseId } },
          body: { lecture_id: lectureId },
        });
        if (!response.ok) throw new ApiError(response.status, error);
      }
      for (const courseId of remove) {
        const { error, response } = await api.DELETE("/api/v1/courses/{course_id}/lectures/{lecture_id}", {
          params: { path: { course_id: courseId, lecture_id: lectureId } },
        });
        if (!response.ok && response.status !== 404) throw new ApiError(response.status, error);
      }
    },
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: lectureCoursesKey(lectureId) }),
        client.invalidateQueries({ queryKey: ["courses"] }),
      ]),
  });
}
