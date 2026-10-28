import assert from "node:assert/strict";
import { test } from "node:test";
import { audioTransferList } from "../src/local/whisper/transfer.ts";

test("transfers PCM backed by an ArrayBuffer", () => {
  const audio = new Float32Array([1, 2]);
  assert.deepEqual(audioTransferList(audio), [audio.buffer]);
});

test("leaves shared PCM buffers out of the transfer list", () => {
  const audio = new Float32Array(new SharedArrayBuffer(Float32Array.BYTES_PER_ELEMENT));
  assert.deepEqual(audioTransferList(audio), []);
});
