export const AUDIO_SAMPLE_RATE = 16000;

export class PcmBuffer {
  private data: Float32Array;
  private size = 0;

  constructor(expectedSeconds: number) {
    const seconds = Number.isFinite(expectedSeconds) && expectedSeconds > 0 ? expectedSeconds : 60;
    this.data = new Float32Array(Math.ceil(seconds * AUDIO_SAMPLE_RATE) + AUDIO_SAMPLE_RATE);
  }

  get length() {
    return this.size;
  }

  append(chunk: Float32Array) {
    if (this.size + chunk.length > this.data.length) {
      const grown = new Float32Array(Math.ceil((this.size + chunk.length) * 1.5));
      grown.set(this.data.subarray(0, this.size));
      this.data = grown;
    }
    this.data.set(chunk, this.size);
    this.size += chunk.length;
  }

  result() {
    return this.data.subarray(0, this.size);
  }
}

export function mixToMono(channels: Float32Array[], frames: number, target: Float32Array) {
  const count = channels.length;
  for (let frame = 0; frame < frames; frame++) {
    let sum = 0;
    for (let channel = 0; channel < count; channel++) sum += channels[channel][frame];
    target[frame] = sum / count;
  }
  return target.subarray(0, frames);
}
