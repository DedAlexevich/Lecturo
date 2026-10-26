const ZERO_CROSSINGS = 8;
const PHASES = 512;
const CUTOFF = 0.95;

function sinc(x: number) {
  if (x === 0) return 1;
  const angle = Math.PI * x;
  return Math.sin(angle) / angle;
}

function blackman(x: number) {
  if (Math.abs(x) >= 1) return 0;
  return 0.42 + 0.5 * Math.cos(Math.PI * x) + 0.08 * Math.cos(2 * Math.PI * x);
}

function buildKernel(halfWidth: number, cutoff: number) {
  const taps = halfWidth * 2;
  const table = new Float32Array((PHASES + 1) * taps);
  for (let phase = 0; phase <= PHASES; phase++) {
    const fraction = phase / PHASES;
    const row = phase * taps;
    let sum = 0;
    for (let tap = 0; tap < taps; tap++) {
      const distance = fraction + halfWidth - 1 - tap;
      const value = sinc(2 * cutoff * distance) * blackman(distance / halfWidth);
      table[row + tap] = value;
      sum += value;
    }
    for (let tap = 0; tap < taps; tap++) table[row + tap] /= sum;
  }
  return table;
}

export class Resampler {
  private readonly step: number;
  private readonly halfWidth: number;
  private readonly kernel: Float32Array;
  private buffer: Float32Array;
  private length: number;
  private position: number;
  private received = 0;
  private produced = 0;

  constructor(inputRate: number, outputRate: number) {
    this.step = inputRate / outputRate;
    const scale = Math.min(1, outputRate / inputRate);
    this.halfWidth = Math.ceil(ZERO_CROSSINGS / scale);
    this.kernel = buildKernel(this.halfWidth, 0.5 * scale * CUTOFF);
    this.buffer = new Float32Array(Math.max(4096, this.halfWidth * 4));
    this.length = this.halfWidth;
    this.position = this.halfWidth;
  }

  push(input: Float32Array) {
    if (this.step === 1) return input.slice();
    this.append(input);
    this.received += input.length;
    return this.drain(Infinity);
  }

  flush() {
    if (this.step === 1) return new Float32Array(0);
    const expected = Math.ceil(this.received / this.step);
    this.append(new Float32Array(this.halfWidth * 2 + Math.ceil(this.step)));
    return this.drain(expected - this.produced);
  }

  private append(input: Float32Array) {
    if (this.length + input.length > this.buffer.length) {
      const grown = new Float32Array(Math.max(this.buffer.length * 2, this.length + input.length));
      grown.set(this.buffer.subarray(0, this.length));
      this.buffer = grown;
    }
    this.buffer.set(input, this.length);
    this.length += input.length;
  }

  private drain(limit: number) {
    const { buffer, kernel, halfWidth, step } = this;
    const taps = halfWidth * 2;
    const available = Math.ceil((this.length - halfWidth - this.position) / step);
    const count = Math.max(0, Math.min(limit, available));
    const output = new Float32Array(count);
    let position = this.position;
    for (let index = 0; index < count; index++) {
      const whole = Math.floor(position);
      const row = Math.round((position - whole) * PHASES) * taps;
      const start = whole - halfWidth + 1;
      let value = 0;
      for (let tap = 0; tap < taps; tap++) value += buffer[start + tap] * kernel[row + tap];
      output[index] = value;
      position += step;
    }
    this.produced += count;
    const drop = Math.max(0, Math.floor(position) - halfWidth + 1);
    buffer.copyWithin(0, drop, this.length);
    this.length -= drop;
    this.position = position - drop;
    return output;
  }
}
