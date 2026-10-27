export const NO_GPU_MESSAGE = "На этом устройстве нет подходящей видеокарты. Конспект можно создать на сервере после сохранения в аккаунт.";

export const REQUIRED_FEATURES: string[] = [];
export const REQUIRED_LIMITS = {
  maxBufferSize: 256 * 1024 * 1024,
  maxStorageBufferBindingSize: 128 * 1024 * 1024,
};

export type GpuVerdict = { ok: true } | { ok: false; reason: "no-adapter" | "software" | "features" | "limits" };

export interface AdapterLike {
  isFallbackAdapter?: boolean;
  features?: { has(name: string): boolean };
  limits?: Record<string, unknown>;
}

export function assessAdapter(adapter: AdapterLike | null | undefined): GpuVerdict {
  if (!adapter) return { ok: false, reason: "no-adapter" };
  if (adapter.isFallbackAdapter) return { ok: false, reason: "software" };
  const features = adapter.features;
  if (REQUIRED_FEATURES.some((name) => !features || !features.has(name))) return { ok: false, reason: "features" };
  const limits = adapter.limits ?? {};
  for (const [name, minimum] of Object.entries(REQUIRED_LIMITS)) {
    const value = limits[name];
    if (typeof value !== "number" || value < minimum) return { ok: false, reason: "limits" };
  }
  return { ok: true };
}

export function friendlyNotesError(message: string): string {
  return /compatible GPU|WebGPU|GPUAdapter|GPUDevice|no GPU/i.test(message) ? NO_GPU_MESSAGE : message;
}

interface GpuDeviceLike { destroy(): void }
interface GpuAdapterLike extends AdapterLike { requestDevice(): Promise<GpuDeviceLike> }
interface GpuLike { requestAdapter(options?: { powerPreference?: string }): Promise<GpuAdapterLike | null> }

let cached: Promise<boolean> | null = null;

async function probe(): Promise<boolean> {
  const gpu = (navigator as Navigator & { gpu?: GpuLike }).gpu;
  if (!gpu) return false;
  try {
    const adapter = await gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter || !assessAdapter(adapter).ok) return false;
    const device = await adapter.requestDevice();
    device.destroy();
    return true;
  } catch {
    return false;
  }
}

export function supportsWebGPU(): Promise<boolean> {
  cached ??= probe();
  return cached;
}
