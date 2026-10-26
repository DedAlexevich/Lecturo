import {
  ALL_FORMATS,
  AudioSample,
  AudioSampleSink,
  AudioSampleSource,
  BlobSource,
  BufferTarget,
  Input,
  type InputAudioTrack,
  Output,
  Quality,
  WebMOutputFormat,
  canEncodeAudio,
} from "mediabunny";
import { AUDIO_SAMPLE_RATE, PcmBuffer, mixToMono } from "./pcm";
import { Resampler } from "./resampler";
import { type ExtractOptions, type ExtractedAudio, NoAudioTrackError, OPUS_BITRATE, OPUS_MIME } from "./types";

const opusQuality = new Quality({ bitrate: OPUS_BITRATE });

type Prepared = { input: Input; track: InputAudioTrack };

export async function prepareWebCodecs(file: Blob, opus: boolean): Promise<Prepared | null> {
  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  let result: Prepared | "no-audio" | null = null;
  try {
    if (await input.canRead()) {
      const track = await input.getPrimaryAudioTrack();
      if (!track) result = "no-audio";
      else if ((await track.canDecode()) && (!opus || (await canEncodeOpus()))) result = { input, track };
    }
  } catch {
    result = null;
  }
  if (result === "no-audio") {
    input.dispose();
    throw new NoAudioTrackError();
  }
  if (!result) input.dispose();
  return result;
}

function canEncodeOpus() {
  return canEncodeAudio("opus", {
    numberOfChannels: 1,
    sampleRate: AUDIO_SAMPLE_RATE,
    quality: opusQuality,
  });
}

function createOpusOutput() {
  const output = new Output({ format: new WebMOutputFormat(), target: new BufferTarget() });
  const source = new AudioSampleSource({ codec: "opus", quality: opusQuality });
  output.addAudioTrack(source);
  return { output, source };
}

export async function extractWithWebCodecs(
  { input, track }: Prepared,
  { opus = false, signal, onProgress }: ExtractOptions,
): Promise<ExtractedAudio> {
  const encoder = opus ? createOpusOutput() : null;
  try {
    const duration = await input.computeDuration([track]);
    const pcm = new PcmBuffer(duration);
    if (encoder) await encoder.output.start();

    const write = async (chunk: Float32Array) => {
      if (chunk.length === 0) return;
      const timestamp = pcm.length / AUDIO_SAMPLE_RATE;
      pcm.append(chunk);
      if (!encoder) return;
      const sample = new AudioSample({
        data: chunk,
        format: "f32-planar",
        numberOfChannels: 1,
        sampleRate: AUDIO_SAMPLE_RATE,
        timestamp,
      });
      await encoder.source.add(sample);
      sample.close();
    };

    let resampler: Resampler | null = null;
    let inputRate = 0;
    let planes: Float32Array[] = [];
    let mono = new Float32Array(0);

    for await (const sample of new AudioSampleSink(track).samples()) {
      try {
        signal?.throwIfAborted();
        const frames = sample.numberOfFrames;
        if (sample.sampleRate !== inputRate || !resampler) {
          if (resampler) await write(resampler.flush());
          inputRate = sample.sampleRate;
          resampler = new Resampler(inputRate, AUDIO_SAMPLE_RATE);
        }
        if (planes.length !== sample.numberOfChannels || planes[0].length < frames) {
          planes = Array.from({ length: sample.numberOfChannels }, () => new Float32Array(frames));
        }
        if (mono.length < frames) mono = new Float32Array(frames);
        planes.forEach((plane, planeIndex) =>
          sample.copyTo(plane.subarray(0, frames), { planeIndex, format: "f32-planar" }),
        );
        await write(resampler.push(mixToMono(planes, frames, mono)));
        if (duration > 0) onProgress?.(Math.min(1, (sample.timestamp + sample.duration) / duration));
      } finally {
        sample.close();
      }
    }
    if (resampler) await write(resampler.flush());

    let blob: Blob | null = null;
    if (encoder) {
      await encoder.output.finalize();
      const buffer = encoder.output.target.buffer;
      blob = buffer ? new Blob([buffer], { type: OPUS_MIME }) : null;
    }
    onProgress?.(1);
    return {
      pcm: pcm.result(),
      sampleRate: AUDIO_SAMPLE_RATE,
      duration: pcm.length / AUDIO_SAMPLE_RATE,
      opus: blob,
      method: "webcodecs",
    };
  } finally {
    if (encoder && encoder.output.state !== "finalized") await encoder.output.cancel();
    input.dispose();
  }
}
