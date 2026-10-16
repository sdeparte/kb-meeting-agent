import assert from "node:assert/strict";
import { test } from "node:test";

import { AUDIO_FRAME, decodeAudioFrame, encodeAudioFrame, message, parseMessage } from "../src/protocol.js";

test("audio frames round-trip with a 64-bit snowflake", () => {
  const pcm = Buffer.from([1, 2, 3, 4]);
  const frame = encodeAudioFrame("18446744073709551615", 1760000000123, pcm);
  assert.equal(frame.length, 21);
  assert.equal(frame[0], AUDIO_FRAME);
  assert.deepEqual(decodeAudioFrame(frame), { userId: "18446744073709551615", timestampMs: 1760000000123, pcm });
});

test("messages carry a type", () => {
  assert.deepEqual(JSON.parse(message("hello", { protocol: 1 })), { type: "hello", protocol: 1 });
  assert.deepEqual(parseMessage('{"type":"join","voice_channel_id":"1"}'), { type: "join", voice_channel_id: "1" });
  assert.throws(() => parseMessage('{"no":"type"}'));
  assert.throws(() => parseMessage("[]"));
});
