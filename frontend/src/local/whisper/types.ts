export type WhisperModel = "tiny" | "base" | "small";

export type WhisperDevice = "webgpu" | "wasm";

export interface Segment {
  start: number;
  end: number;
  text: string;
}

export interface TranscribeProgress {
  stage: "loading" | "transcribing";
  value: number;
}

export type ProgressHandler = (progress: TranscribeProgress) => void;

export interface TranscribeOptions {
  language?: string;
  signal?: AbortSignal;
}

export interface WorkerRequest {
  id: number;
  audio: Float32Array;
  model: WhisperModel;
  device: WhisperDevice;
  language?: string;
}

export type WorkerResponse =
  | { id: number; type: "progress"; progress: TranscribeProgress }
  | { id: number; type: "done"; segments: Segment[] }
  | { id: number; type: "error"; message: string };
