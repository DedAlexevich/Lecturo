import type { WhisperModel } from "./types";

export const SAMPLE_RATE = 16000;

export const WHISPER_MODELS: Record<WhisperModel, { repo: string; sizeMb: number }> = {
  tiny: { repo: "onnx-community/whisper-tiny", sizeMb: 150 },
  base: { repo: "onnx-community/whisper-base", sizeMb: 290 },
  small: { repo: "onnx-community/whisper-small", sizeMb: 900 },
};
