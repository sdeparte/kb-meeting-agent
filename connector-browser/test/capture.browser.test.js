// Runs the capture script in a real headless Chromium on a local WebRTC call (two peer
// connections in one page, a 440 Hz tone): proves the call's audio reaches Node at 16 kHz.
// Skipped when Playwright's Chromium is not installed (`npx playwright install chromium`).
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { chromium } from "playwright";

import { captureAudio, openBrowser } from "../src/browser.js";
import { rmsDbfs } from "../src/pcm.js";

// `send`: how the tone is sent. "native": by the native RTCPeerConnection, as a remote
// participant's browser does; "addTrack" / "addTransceiver": by the page's own (wrapped) one,
// as the agent's microphone would be. "microphone": the agent's fake microphone itself, that
// the page switches back on and sends by the native connection.
const call = (send) => `<script>
(async () => {
  const send = ${JSON.stringify(send)};
  const native = send === "native" || send === "microphone";
  const Sender = native ? window.__kbmaNativeRTCPeerConnection : RTCPeerConnection;
  const sender = new Sender();
  const receiver = new RTCPeerConnection();
  sender.onicecandidate = (e) => e.candidate && receiver.addIceCandidate(e.candidate);
  receiver.onicecandidate = (e) => e.candidate && sender.addIceCandidate(e.candidate);
  let stream;
  if (send === "microphone") {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getAudioTracks()[0].enabled = true;
  } else {
    const audio = new AudioContext();
    const tone = audio.createOscillator();
    const out = audio.createMediaStreamDestination();
    tone.frequency.value = 440;
    tone.connect(out);
    tone.start();
    stream = out.stream;
  }
  const track = stream.getAudioTracks()[0];
  if (send === "addTransceiver") sender.addTransceiver(track, { direction: "sendonly" });
  else sender.addTrack(track, stream);
  await sender.setLocalDescription(await sender.createOffer());
  await receiver.setRemoteDescription(sender.localDescription);
  await receiver.setLocalDescription(await receiver.createAnswer());
  await sender.setRemoteDescription(receiver.localDescription);
})();
</script>`;

async function capture(send, headers = {}) {
  // 127.0.0.1: a secure context, as the real https meeting pages are (the capture script does
  // nothing elsewhere)
  const server = createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/html", ...headers });
    res.end(`<!doctype html>${call(send)}`);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const profileDir = mkdtempSync(join(tmpdir(), "kbma-profile-"));
  const { context, page } = await openBrowser({ profileDir });
  const blocks = [];
  try {
    await captureAudio(page, (samples) => blocks.push(samples));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    const deadline = Date.now() + 6_000;
    while (!blocks.some((b) => rmsDbfs(b) > -30) && Date.now() < deadline) await page.waitForTimeout(200);
  } finally {
    await context.close();
    server.close();
    rmSync(profileDir, { recursive: true, force: true });
  }
  return blocks;
}

const noBrowser = !existsSync(chromium.executablePath());

test("a participant's audio reaches Node in 20 ms blocks at 16 kHz", { skip: noBrowser }, async () => {
  const blocks = await capture("native");
  assert.ok(blocks.length > 0, "no audio block reached Node");
  assert.equal(blocks[0].length, 320);
  assert.ok(blocks.some((b) => rmsDbfs(b) > -30), "the tone was not heard");
});

for (const send of ["addTrack", "addTransceiver", "microphone"]) {
  test(`the agent's own microphone sends no sound into the call (${send})`, { skip: noBrowser }, async () => {
    const blocks = await capture(send);
    assert.ok(blocks.length > 0);
    assert.ok(blocks.every((b) => rmsDbfs(b) < -60));
  });
}

test("a page whose CSP forbids blob: scripts is still captured", { skip: noBrowser }, async () => {
  const csp = { "content-security-policy": "script-src 'self' 'unsafe-inline'; worker-src 'self'" };
  const blocks = await capture("native", csp);
  assert.ok(blocks.some((b) => rmsDbfs(b) > -30), "the tone was not heard");
});

test("microphone tracks the page asks for are disabled, and stay so", { skip: noBrowser }, async () => {
  const profileDir = mkdtempSync(join(tmpdir(), "kbma-profile-"));
  const server = createServer((_req, res) => res.end("<!doctype html><p>call</p>"));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { context, page } = await openBrowser({ profileDir });
  try {
    await captureAudio(page, () => {});
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    const enabled = await page.evaluate(async () => {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const [track] = stream.getAudioTracks();
      const before = track.enabled;
      track.enabled = true; // the page's own unmute: does nothing, does not throw
      return [before, track.enabled];
    });
    assert.deepEqual(enabled, [false, false]);
  } finally {
    await context.close();
    server.close();
    rmSync(profileDir, { recursive: true, force: true });
  }
});
