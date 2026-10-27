import { useMutation, useQueryClient } from "@tanstack/react-query";
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

export function useRegenerateSummary(lectureId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/v1/lectures/{lecture_id}/regenerate-summary", {
        params: { path: { lecture_id: lectureId } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: async (status) => {
      client.setQueryData(["lecture-status", lectureId], status);
      await client.invalidateQueries({ queryKey: ["lectures", lectureId], exact: true });
    },
  });
}
