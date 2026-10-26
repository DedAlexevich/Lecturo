import { pipeline, type AutomaticSpeechRecognitionPipeline } from "@huggingface/transformers";
import { SAMPLE_RATE, WHISPER_MODELS } from "./models";
import type { Segment, WhisperDevice, WhisperModel, WorkerRequest, WorkerResponse } from "./types";

const BLOCK_SECONDS = 120;
const CHUNK_SECONDS = 30;
const STRIDE_SECONDS = 5;

type Recognizer = AutomaticSpeechRecognitionPipeline;

let loaded: { key: string; recognizer: Recognizer } | null = null;
let queue: Promise<void> = Promise.resolve();

function post(message: WorkerResponse) {
  self.postMessage(message);
}

async function loadRecognizer(
  id: number,
  model: WhisperModel,
  device: WhisperDevice,
): Promise<Recognizer> {
  const key = `${model}:${device}`;
  if (loaded?.key === key) return loaded.recognizer;
  loaded = null;

  const files = new Map<string, { loaded: number; total: number }>();
  const recognizer = (await pipeline("automatic-speech-recognition", WHISPER_MODELS[model].repo, {
    device,
    dtype:
      device === "webgpu"
        ? { encoder_model: "fp32", decoder_model_merged: "q4" }
        : { encoder_model: "q8", decoder_model_merged: "q8" },
    progress_callback: (event) => {
      if (event.status !== "progress") return;
      files.set(event.file, { loaded: event.loaded, total: event.total });
      let done = 0;
      let total = 0;
      for (const file of files.values()) {
        done += file.loaded;
        total += file.total;
      }
      post({
        id,
        type: "progress",
        progress: { stage: "loading", value: total > 0 ? done / total : 0 },
      });
    },
  })) as Recognizer;

  loaded = { key, recognizer };
  return recognizer;
}

async function run(request: WorkerRequest) {
  const { id, audio, model, device, language } = request;
  try {
    const recognizer = await loadRecognizer(id, model, device);
    post({ id, type: "progress", progress: { stage: "loading", value: 1 } });

    const blockSize = BLOCK_SECONDS * SAMPLE_RATE;
    const segments: Segment[] = [];
    post({ id, type: "progress", progress: { stage: "transcribing", value: 0 } });

    for (let from = 0; from < audio.length; from += blockSize) {
      const block = audio.subarray(from, Math.min(from + blockSize, audio.length));
      const offset = from / SAMPLE_RATE;
      const result = await recognizer(block, {
        return_timestamps: true,
        chunk_length_s: CHUNK_SECONDS,
        stride_length_s: STRIDE_SECONDS,
        language,
        task: "transcribe",
      });
      const output = Array.isArray(result) ? result[0] : result;
      for (const chunk of output.chunks ?? []) {
        const text = chunk.text.trim();
        if (!text) continue;
        const [start, end] = chunk.timestamp;
        const blockEnd = offset + block.length / SAMPLE_RATE;
        segments.push({
          start: offset + start,
          end: end === null ? blockEnd : offset + end,
          text,
        });
      }
      post({
        id,
        type: "progress",
        progress: { stage: "transcribing", value: Math.min(1, (from + block.length) / audio.length) },
      });
    }

    post({ id, type: "done", segments });
  } catch (error) {
    post({ id, type: "error", message: error instanceof Error ? error.message : String(error) });
  }
}

self.onmessage = (event: MessageEvent<WorkerRequest>) => {
  queue = queue.then(() => run(event.data));
};
