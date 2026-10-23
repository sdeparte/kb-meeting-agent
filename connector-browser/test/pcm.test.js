import assert from "node:assert/strict";
import { test } from "node:test";

import { floatToPcm16, rmsDbfs } from "../src/pcm.js";

test("float samples become clamped 16-bit little-endian PCM", () => {
  const pcm = floatToPcm16(Float32Array.of(0, 1, -1, 2));
  const expected = Buffer.alloc(8);
  [0, 32767, -32767, 32767].forEach((v, i) => expected.writeInt16LE(v, i * 2));
  assert.deepEqual(pcm, expected);
});

test("the level of a 0.1 square wave is -20 dBFS", () => {
  const samples = Float32Array.from({ length: 320 }, (_, i) => (i % 2 ? 0.1 : -0.1));
  assert.ok(Math.abs(rmsDbfs(samples) + 20) < 0.5);
  assert.equal(rmsDbfs(new Float32Array(320)), -Infinity);
});
