import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type Course = components["schemas"]["CourseOut"];
export type LinkIn = components["schemas"]["LinkIn"];

export function useCourseOptions(enabled: boolean) {
  return useQuery({
    queryKey: ["courses"],
    enabled,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/courses");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useAddLink() {
  return useMutation({
    mutationFn: async (body: LinkIn) => {
      const { data, error, response } = await api.POST("/api/v1/lectures/link", { body });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}
