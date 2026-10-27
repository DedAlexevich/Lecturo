import type { LlmPrecision } from "./types";

type GpuAdapter = { features: { has(name: string): boolean } };
type Gpu = { requestAdapter(): Promise<GpuAdapter | null> };

let detected: Promise<LlmPrecision | null> | null = null;

async function detect(): Promise<LlmPrecision | null> {
  const gpu = (navigator as Navigator & { gpu?: Gpu }).gpu;
  if (!gpu) return null;
  try {
    const adapter = await gpu.requestAdapter();
    if (!adapter) return null;
    return adapter.features.has("shader-f16") ? "f16" : "f32";
  } catch {
    return null;
  }
}

export function detectLlmPrecision(): Promise<LlmPrecision | null> {
  detected ??= detect();
  return detected;
}
