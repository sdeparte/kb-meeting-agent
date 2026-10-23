// Chromium for a browser-driven connector: a persistent profile (logged in once by hand with
// the connector's `npm run login`), fake devices whose microphone plays silence, and the call's
// audio captured in-page.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

import { CAPTURE_SCRIPT } from "./capture.js";

// Chromium's own fake microphone beeps: it plays this file instead.
export function launchArgs(fakeAudioFile) {
  return [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${fakeAudioFile}`,
    "--autoplay-policy=no-user-gesture-required",
  ];
}

// One second of 16-bit mono silence, as a WAV file.
export function silentWav(rate = 16000) {
  const data = rate * 2;
  const wav = Buffer.alloc(44 + data);
  wav.write("RIFF", 0);
  wav.writeUInt32LE(36 + data, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16); // fmt chunk size
  wav.writeUInt16LE(1, 20); // PCM
  wav.writeUInt16LE(1, 22); // mono
  wav.writeUInt32LE(rate, 24);
  wav.writeUInt32LE(rate * 2, 28); // bytes per second
  wav.writeUInt16LE(2, 32); // bytes per frame
  wav.writeUInt16LE(16, 34); // bits per sample
  wav.write("data", 36);
  wav.writeUInt32LE(data, 40);
  return wav;
}

export async function openBrowser({ profileDir, headless = true, viewport = { width: 1280, height: 800 } }) {
  mkdirSync(profileDir, { recursive: true });
  const silence = join(profileDir, "kbma-silence.wav");
  writeFileSync(silence, silentWav());
  const context = await chromium.launchPersistentContext(profileDir, {
    headless,
    viewport,
    args: launchArgs(silence),
    permissions: ["microphone", "camera"],
  });
  const page = context.pages()[0] ?? (await context.newPage());
  return { context, page };
}

const BLOCK = 320; // 20 ms at 16 kHz, as the capture script sends them

// The binding is visible to every script of the page: only the main frame's well-formed
// blocks are taken, and the time is Node's, not the page's.
export function acceptedBlock(source, samples, mainFrame) {
  if (source.frame !== mainFrame || !Array.isArray(samples) || samples.length !== BLOCK) return null;
  if (!samples.every((s) => typeof s === "number" && Number.isFinite(s))) return null;
  return Float32Array.from(samples);
}

// Call before the meeting page loads: the script must wrap RTCPeerConnection first.
export async function captureAudio(page, onSamples, log = () => {}) {
  page.on("console", (message) => {
    if (message.text().startsWith("kbma:")) log(message.text());
  });
  await page.exposeBinding("__kbmaAudio", (source, samples) => {
    const block = acceptedBlock(source, samples, page.mainFrame());
    if (block) onSamples(block, Date.now());
  });
  await page.addInitScript(CAPTURE_SCRIPT);
}
