import assert from "node:assert/strict";
import { test } from "node:test";

import { AUDIO_FRAME, PROTOCOL_VERSION, decodeAudioFrame, encodeAudioFrame, message, parseMessage } from "../src/protocol.js";

test("protocol version 2", () => {
  assert.equal(PROTOCOL_VERSION, 2);
});

for (const userId of ["18446744073709551615", "U0123ABCD", "spaces/abc-defg-hij/participants/9f8e7d", "Zoé"]) {
  test(`audio frames round-trip with the speaker id ${userId}`, () => {
    const pcm = Buffer.from([1, 2, 3, 4]);
    const frame = encodeAudioFrame(userId, 1760000000123, pcm);
    assert.equal(frame.length, 10 + Buffer.byteLength(userId) + 4);
    assert.equal(frame[0], AUDIO_FRAME);
    assert.deepEqual(decodeAudioFrame(frame), { userId, timestampMs: 1760000000123, pcm });
  });
}

test("speaker ids are 1 to 255 bytes", () => {
  assert.throws(() => encodeAudioFrame("", 0, Buffer.alloc(0)));
  assert.throws(() => encodeAudioFrame("x".repeat(256), 0, Buffer.alloc(0)));
  assert.throws(() => decodeAudioFrame(Buffer.from([AUDIO_FRAME, 0, 0, 0, 0, 0, 0, 0, 0, 5, 97])));
});

test("messages carry a type", () => {
  assert.deepEqual(JSON.parse(message("hello", { protocol: 1 })), { type: "hello", protocol: 1 });
  assert.deepEqual(parseMessage('{"type":"join","voice_channel_id":"1"}'), { type: "join", voice_channel_id: "1" });
  assert.throws(() => parseMessage('{"no":"type"}'));
  assert.throws(() => parseMessage("[]"));
});
