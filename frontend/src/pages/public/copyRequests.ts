import { api } from "../../api/client";
import type { ExportFormat, LinkResult } from "../lecture/ExportActions";

export type CopyResult =
  | { kind: "saved"; created: boolean; lectureId: string | null; courseId: string | null }
  | { kind: "own"; lectureId: string | null; courseId: string | null }
  | { kind: "failed"; status: number; message: string | null };

type ConflictDetail = { lecture_id?: string | null; course_id?: string | null };

function detailOf(error: unknown): unknown {
  return (error as { detail?: unknown } | undefined)?.detail;
}

function messageOf(error: unknown): string | null {
  const detail = detailOf(error);
  if (typeof detail === "string") return detail;
  const message = (detail as { message?: unknown } | undefined)?.message;
  return typeof message === "string" ? message : null;
}

export async function copyShared(token: string, lectureId: string | null): Promise<CopyResult> {
  const { data, error, response } = await api.POST("/api/v1/public/{token}/copy", {
    params: { path: { token } },
    body: lectureId === null ? null : { lecture_id: lectureId },
  });
  if (data !== undefined) {
    return { kind: "saved", created: data.created, lectureId: data.lecture_id, courseId: data.course_id };
  }
  if (response.status === 409) {
    const detail = detailOf(error) as ConflictDetail | undefined;
    return { kind: "own", lectureId: detail?.lecture_id ?? null, courseId: detail?.course_id ?? null };
  }
  return { kind: "failed", status: response.status, message: messageOf(error) };
}

export async function requestPublicLink(token: string, lectureId: string, format: ExportFormat): Promise<LinkResult> {
  const { data, response } = await api.POST("/api/v1/public/{token}/lectures/{lecture_id}/exports/{export_format}/link", {
    params: { path: { token, lecture_id: lectureId, export_format: format } },
  });
  return data === undefined ? response.status : data;
}
