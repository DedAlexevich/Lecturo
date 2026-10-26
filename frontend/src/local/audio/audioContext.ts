import { AUDIO_SAMPLE_RATE, mixToMono } from "./pcm";
import type { ExtractOptions, ExtractedAudio } from "./types";

const MAX_FILE_SIZE = 100 * 1024 * 1024;

export function canUseAudioContext(file: Blob, opus: boolean) {
  return !opus && file.size <= MAX_FILE_SIZE && typeof OfflineAudioContext !== "undefined";
}

export async function extractWithAudioContext(
  file: Blob,
  { signal, onProgress }: ExtractOptions,
): Promise<ExtractedAudio> {
  const data = await file.arrayBuffer();
  signal?.throwIfAborted();
  const decoded = await new OfflineAudioContext(1, 1, AUDIO_SAMPLE_RATE).decodeAudioData(data);
  signal?.throwIfAborted();
  const channels = Array.from({ length: decoded.numberOfChannels }, (_, index) => decoded.getChannelData(index));
  const pcm =
    channels.length === 1 ? channels[0] : mixToMono(channels, decoded.length, new Float32Array(decoded.length));
  onProgress?.(1);
  return {
    pcm,
    sampleRate: AUDIO_SAMPLE_RATE,
    duration: decoded.duration,
    opus: null,
    method: "audiocontext",
  };
}
