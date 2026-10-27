import type { LlmPrecision } from "./types";

export const LLM_MODEL = {
  label: "Qwen3 1.7B",
  size: "около 1 ГБ",
  ids: {
    f16: "Qwen3-1.7B-q4f16_1-MLC",
    f32: "Qwen3-1.7B-q4f32_1-MLC",
  } satisfies Record<LlmPrecision, string>,
};
