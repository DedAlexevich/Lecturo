import { useEffect, useRef, useState } from "react";
import { tokenStorage } from "../../../api/client";
import type { LogLevel, LogLine, LogService } from "./logsApi";

export const streamLineLimit = 2000;

type StreamState = "idle" | "connecting" | "live" | "error";

type Frame = { event: string; data: string; id: string | null };

function parseFrames(buffer: string): { frames: Frame[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const frames: Frame[] = [];
  for (const part of parts) {
    let event = "message";
    let id: string | null = null;
    const data: string[] = [];
    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("id:")) id = line.slice(3).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length > 0) frames.push({ event, data: data.join("\n"), id });
  }
  return { frames, rest };
}

type Options = {
  service: LogService;
  level: LogLevel | "";
  query: string;
  active: boolean;
  onLines: (lines: LogLine[], restarted: boolean) => void;
  startOffset: number | null;
};

export function useLogStream({ service, level, query, active, onLines, startOffset }: Options) {
  const [state, setState] = useState<StreamState>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const handler = useRef(onLines);
  const start = useRef(startOffset);

  useEffect(() => {
    handler.current = onLines;
    start.current = startOffset;
  });

  useEffect(() => {
    if (!active) {
      setState("idle");
      return;
    }
    const controller = new AbortController();
    let offset = start.current;
    let stopped = false;

    const run = async () => {
      while (!stopped) {
        setState("connecting");
        setMessage(null);
        const params = new URLSearchParams({ q: query });
        if (level) params.set("level", level);
        if (offset !== null) params.set("offset", String(offset));
        let ended = false;
        try {
          const response = await fetch(`/api/v1/admin/logs/${service}/stream?${params}`, {
            headers: { Authorization: `Bearer ${tokenStorage.get() ?? ""}`, Accept: "text/event-stream" },
            signal: controller.signal,
          });
          if (!response.ok || !response.body) {
            setState("error");
            setMessage(response.status === 404 ? "Лог недоступен" : "Не удалось открыть поток");
            return;
          }
          setState("live");
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parsed = parseFrames(buffer);
            buffer = parsed.rest;
            for (const frame of parsed.frames) {
              const payload = JSON.parse(frame.data) as { lines?: LogLine[]; restarted?: boolean; detail?: string };
              if (frame.event === "lines") {
                if (frame.id !== null) offset = Number(frame.id);
                handler.current(payload.lines ?? [], payload.restarted ?? false);
              } else if (frame.event === "error") {
                setState("error");
                setMessage(payload.detail ?? "Поток остановлен");
                return;
              } else if (frame.event === "end") {
                ended = true;
              }
            }
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          setState("error");
          setMessage(error instanceof Error ? "Соединение потеряно" : "Поток остановлен");
          return;
        }
        if (!ended) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
    };

    void run();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [active, service, level, query]);

  return { state, message };
}
