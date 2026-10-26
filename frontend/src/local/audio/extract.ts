import { canUseAudioContext, extractWithAudioContext } from "./audioContext";
import { type ExtractOptions, type ExtractedAudio, NoAudioTrackError } from "./types";
import { extractWithWebCodecs, prepareWebCodecs } from "./webcodecs";

function canFallBack(error: unknown, signal?: AbortSignal) {
  return !signal?.aborted && !(error instanceof NoAudioTrackError);
}

export async function extractAudio(file: Blob, options: ExtractOptions = {}): Promise<ExtractedAudio> {
  options.signal?.throwIfAborted();
  const opus = options.opus ?? false;
  const prepared = await prepareWebCodecs(file, opus);
  if (prepared) {
    try {
      return await extractWithWebCodecs(prepared, options);
    } catch (error) {
      if (!canFallBack(error, options.signal)) throw error;
    }
  }
  options.signal?.throwIfAborted();
  if (canUseAudioContext(file, opus)) {
    try {
      return await extractWithAudioContext(file, options);
    } catch (error) {
      if (!canFallBack(error, options.signal)) throw error;
    }
  }
  const { extractWithFfmpeg } = await import("./ffmpeg");
  return extractWithFfmpeg(file, options);
}
