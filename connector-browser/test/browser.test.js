import assert from "node:assert/strict";
import { test } from "node:test";

import { acceptedBlock, launchArgs, silentWav } from "../src/browser.js";
import { CAPTURE_SCRIPT } from "../src/capture.js";

test("Chromium gets fake devices whose microphone plays a file, and may play audio without a gesture", () => {
  const args = launchArgs("/profile/kbma-silence.wav");
  for (const flag of [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--use-file-for-fake-audio-capture=/profile/kbma-silence.wav",
    "--autoplay-policy=no-user-gesture-required",
  ]) {
    assert.ok(args.includes(flag), flag);
  }
});

test("the fake microphone's file is a second of 16-bit mono silence", () => {
  const wav = silentWav(16000);
  assert.equal(wav.toString("ascii", 0, 4), "RIFF");
  assert.equal(wav.toString("ascii", 8, 16), "WAVEfmt ");
  assert.equal(wav.readUInt16LE(22), 1); // mono
  assert.equal(wav.readUInt32LE(24), 16000);
  assert.equal(wav.readUInt16LE(34), 16);
  assert.equal(wav.readUInt32LE(40), 32000);
  assert.ok(wav.subarray(44).every((byte) => byte === 0));
});

test("the capture script taps the call's remote audio at 16 kHz", () => {
  assert.match(CAPTURE_SCRIPT, /RTCPeerConnection/);
  assert.match(CAPTURE_SCRIPT, /sampleRate: 16000/);
  assert.match(CAPTURE_SCRIPT, /__kbmaAudio/);
  assert.doesNotMatch(CAPTURE_SCRIPT, /blob:|audioWorklet/); // nothing a page's CSP could block
  assert.doesNotThrow(() => new Function(CAPTURE_SCRIPT)); // valid JavaScript
});

test("only well-formed blocks from the main frame are accepted", () => {
  const main = {};
  const block = Array.from({ length: 320 }, () => 0.1);
  assert.ok(acceptedBlock({ frame: main }, block, main) instanceof Float32Array);
  assert.equal(acceptedBlock({ frame: {} }, block, main), null); // an iframe
  assert.equal(acceptedBlock({ frame: main }, block.slice(1), main), null);
  assert.equal(acceptedBlock({ frame: main }, [...block.slice(1), "x"], main), null);
  assert.equal(acceptedBlock({ frame: main }, [...block.slice(1), Infinity], main), null);
  assert.equal(acceptedBlock({ frame: main }, "not an array", main), null);
});
