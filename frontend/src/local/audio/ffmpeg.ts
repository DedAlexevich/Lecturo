import coreURL from "@ffmpeg/core?url";
import wasmURL from "@ffmpeg/core/wasm?url";
import { FFFSType, FFmpeg } from "@ffmpeg/ffmpeg";
import { AUDIO_SAMPLE_RATE } from "./pcm";
import { type ExtractOptions, type ExtractedAudio, NoAudioTrackError, OPUS_BITRATE, OPUS_MIME } from "./types";

const INPUT_DIR = "/input";
const PCM_PATH = "/audio.pcm";
const OPUS_PATH = "/audio.webm";

function inputName(file: Blob) {
  const extension = file instanceof File ? /\.[a-z0-9]{1,5}$/i.exec(file.name)?.[0] : undefined;
  return `source${extension ?? ""}`;
}

function asBytes(data: Uint8Array | string) {
  if (typeof data === "string") throw new Error("Не удалось прочитать извлечённый звук");
  return data;
}

export async function extractWithFfmpeg(
  file: Blob,
  { opus = false, signal, onProgress }: ExtractOptions,
): Promise<ExtractedAudio> {
  signal?.throwIfAborted();
  const ffmpeg = new FFmpeg();
  const abort = () => ffmpeg.terminate();
  signal?.addEventListener("abort", abort, { once: true });
  let missingAudio = false;
  ffmpeg.on("log", ({ message }) => {
    if (message.includes("matches no streams")) missingAudio = true;
  });
  ffmpeg.on("progress", ({ progress }) => {
    if (progress >= 0) onProgress?.(Math.min(1, progress));
  });

  try {
    await ffmpeg.load({ coreURL, wasmURL });
    await ffmpeg.createDir(INPUT_DIR);
    const name = inputName(file);
    await ffmpeg.mount(FFFSType.WORKERFS, { files: [new File([file], name)] }, INPUT_DIR);

    const mono = ["-map", "0:a:0", "-ac", "1", "-ar", String(AUDIO_SAMPLE_RATE)];
    const args = ["-nostdin", "-i", `${INPUT_DIR}/${name}`, ...mono, "-f", "f32le", PCM_PATH];
    if (opus) {
      args.push(...mono, "-c:a", "libopus", "-b:a", String(OPUS_BITRATE), "-application", "voip", OPUS_PATH);
    }
    const code = await ffmpeg.exec(args);
    if (code !== 0) {
      if (missingAudio) throw new NoAudioTrackError();
      throw new Error("Не удалось извлечь звук из файла");
    }

    const raw = asBytes(await ffmpeg.readFile(PCM_PATH));
    const aligned = raw.byteOffset % 4 === 0 ? raw : raw.slice();
    const pcm = new Float32Array(aligned.buffer, aligned.byteOffset, Math.floor(aligned.byteLength / 4));
    const encoded = opus ? new Blob([asBytes(await ffmpeg.readFile(OPUS_PATH))], { type: OPUS_MIME }) : null;
    onProgress?.(1);
    return {
      pcm,
      sampleRate: AUDIO_SAMPLE_RATE,
      duration: pcm.length / AUDIO_SAMPLE_RATE,
      opus: encoded,
      method: "ffmpeg",
    };
  } catch (error) {
    signal?.throwIfAborted();
    throw error;
  } finally {
    signal?.removeEventListener("abort", abort);
    ffmpeg.terminate();
  }
}
