export type ExtractMethod = "webcodecs" | "audiocontext" | "ffmpeg";

export type ExtractOptions = {
  opus?: boolean;
  signal?: AbortSignal;
  onProgress?: (value: number) => void;
};

export type ExtractedAudio = {
  pcm: Float32Array;
  sampleRate: number;
  duration: number;
  opus: Blob | null;
  method: ExtractMethod;
};

export const OPUS_BITRATE = 24000;
export const OPUS_MIME = "audio/webm";

export class NoAudioTrackError extends Error {
  constructor() {
    super("В файле нет звуковой дорожки");
    this.name = "NoAudioTrackError";
  }
}
