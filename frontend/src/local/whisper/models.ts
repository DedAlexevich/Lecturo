import type { WhisperModel } from "./types";

export const SAMPLE_RATE = 16000;

export const WHISPER_MODELS: Record<WhisperModel, { repo: string }> = {
  tiny: { repo: "onnx-community/whisper-tiny" },
  base: { repo: "onnx-community/whisper-base" },
  small: { repo: "onnx-community/whisper-small" },
};
