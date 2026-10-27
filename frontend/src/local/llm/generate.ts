import type { WebWorkerMLCEngine } from "@mlc-ai/web-llm";
import type { LocalSegment } from "../storage/types";
import { detectLlmPrecision } from "./device";
import { LLM_MODEL } from "./models";
import {
  buildOutline,
  digestRequest,
  formatPart,
  groupDigests,
  parseJson,
  splitIntoParts,
  toDigest,
  type Outline,
  type PartDigest,
} from "./outline";
import { MAP_PROMPT, MAP_SCHEMA, REDUCE_PROMPT, REDUCE_SCHEMA } from "./prompts";
import type { OutlineProgressHandler } from "./types";

const ATTEMPTS = 2;
const MAP_TOKENS = 700;
const REDUCE_TOKENS = 1800;

let worker: Worker | null = null;
let engine: Promise<WebWorkerMLCEngine> | null = null;
let engineModel = "";
let onLoadProgress: ((value: number) => void) | null = null;

export function disposeLlm() {
  worker?.terminate();
  worker = null;
  engine = null;
  engineModel = "";
}

function getEngine(modelId: string): Promise<WebWorkerMLCEngine> {
  if (engine && engineModel === modelId) return engine;
  disposeLlm();
  worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  engineModel = modelId;
  const target = worker;
  const created = import("@mlc-ai/web-llm").then(({ CreateWebWorkerMLCEngine }) =>
    CreateWebWorkerMLCEngine(target, modelId, {
      logLevel: "WARN",
      initProgressCallback: (report) => onLoadProgress?.(report.progress),
    }),
  );
  engine = created;
  created.catch(() => {
    if (engine === created) disposeLlm();
  });
  return created;
}

function abortable<T>(promise: Promise<T>, signal: AbortSignal | undefined, onAbort: () => void): Promise<T> {
  if (!signal) return promise;
  return new Promise<T>((resolve, reject) => {
    const abort = () => {
      onAbort();
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    };
    if (signal.aborted) {
      abort();
      return;
    }
    signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

async function complete(
  target: WebWorkerMLCEngine,
  system: string,
  user: string,
  schema: string,
  maxTokens: number,
  signal?: AbortSignal,
): Promise<Record<string, unknown> | null> {
  for (let attempt = 0; attempt < ATTEMPTS; attempt += 1) {
    signal?.throwIfAborted();
    const reply = await abortable(
      target.chat.completions.create({
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        temperature: 0.3,
        max_tokens: maxTokens,
        response_format: { type: "json_object", schema },
        extra_body: { enable_thinking: false },
      }),
      signal,
      () => target.interruptGenerate(),
    );
    const data = parseJson(reply.choices[0]?.message.content ?? "");
    if (data) return data;
  }
  return null;
}

export async function buildLectureOutline(
  title: string,
  segments: LocalSegment[],
  onProgress?: OutlineProgressHandler,
  signal?: AbortSignal,
): Promise<Outline> {
  signal?.throwIfAborted();
  const precision = await detectLlmPrecision();
  if (!precision) throw new Error("Браузер не поддерживает WebGPU");
  const ordered = [...segments].filter((segment) => segment.text.trim()).sort((a, b) => a.start - b.start);
  if (ordered.length === 0) return { chapters: [], summaryMd: "" };

  onProgress?.({ stage: "loading", value: 0 });
  onLoadProgress = (value) => onProgress?.({ stage: "loading", value });
  let target: WebWorkerMLCEngine;
  try {
    target = await abortable(getEngine(LLM_MODEL.ids[precision]), signal, disposeLlm);
  } finally {
    onLoadProgress = null;
  }

  const parts = splitIntoParts(ordered);
  let total = parts.length + 1;
  let done = 0;
  const step = () => {
    done += 1;
    onProgress?.({ stage: "outlining", value: Math.min(1, done / total) });
  };
  onProgress?.({ stage: "outlining", value: 0 });

  const digests: PartDigest[] = [];
  for (const part of parts) {
    const data = await complete(target, MAP_PROMPT, formatPart(part), MAP_SCHEMA, MAP_TOKENS, signal);
    digests.push(toDigest(part, data));
    step();
  }

  const groups = groupDigests(title, digests);
  total = parts.length + groups.length;
  const reductions: (Record<string, unknown> | null)[] = [];
  for (const group of groups) {
    reductions.push(await complete(target, REDUCE_PROMPT, digestRequest(title, group), REDUCE_SCHEMA, REDUCE_TOKENS, signal));
    step();
  }

  return buildOutline(reductions, ordered, digests);
}
