import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, tokenStorage } from "../../../api/client";
import type { components } from "../../../api/schema";
import { ApiError } from "../../../app/queryClient";

export type ZoomerVideo = components["schemas"]["ZoomerVideoOut"];
export type ZoomerVideoPatch = components["schemas"]["ZoomerVideoPatch"];

export const zoomerQueryKey = ["admin", "zoomer"] as const;

export function useZoomerVideos() {
  return useQuery({
    queryKey: zoomerQueryKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/zoomer/videos");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    refetchInterval: (query) => (query.state.data?.some((video) => video.status === "processing") ? 3000 : false),
  });
}

export function useUpdateZoomerVideo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: ZoomerVideoPatch }) => {
      const { data, error, response } = await api.PATCH("/api/v1/admin/zoomer/videos/{video_id}", {
        params: { path: { video_id: id } },
        body: patch,
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: zoomerQueryKey }),
  });
}

export function useReorderZoomerVideos() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[]) => {
      const { data, error, response } = await api.PUT("/api/v1/admin/zoomer/order", { body: { ids } });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (data) => queryClient.setQueryData(zoomerQueryKey, data),
  });
}

export function useDeleteZoomerVideo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error, response } = await api.DELETE("/api/v1/admin/zoomer/videos/{video_id}", {
        params: { path: { video_id: id } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: zoomerQueryKey }),
  });
}

export function uploadZoomerVideo(
  file: File,
  fields: { title: string; source: string },
  onProgress: (share: number) => void,
) {
  return new Promise<ZoomerVideo>((resolve, reject) => {
    const query = new URLSearchParams(fields);
    const request = new XMLHttpRequest();
    request.open("POST", `/api/v1/admin/zoomer/videos?${query}`);
    request.setRequestHeader("Authorization", `Bearer ${tokenStorage.get() ?? ""}`);
    request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onerror = () => reject(new ApiError(0, undefined));
    request.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        body = undefined;
      }
      if (request.status >= 200 && request.status < 300) resolve(body as ZoomerVideo);
      else reject(new ApiError(request.status, body));
    };
    request.send(file);
  });
}

export function formatDuration(seconds: number | null) {
  if (seconds === null) return "—";
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
