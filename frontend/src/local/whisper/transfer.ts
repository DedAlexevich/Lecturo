export function audioTransferList(audio: Float32Array): Transferable[] {
  return audio.buffer instanceof ArrayBuffer ? [audio.buffer] : [];
}
