# connector-browser

A library, not a connector: it is never started on its own. It holds what the connectors that drive a web meeting client in a browser share:

- `browser.js`: launch Chromium (Playwright) on a persistent profile, with a silent fake microphone and camera, and capture the call's audio inside the page, mixed and resampled to 16 kHz;
- `speakers.js`: turn that mixed audio and the platform's "who is speaking" indicator into per-speaker utterances for the core;
- `pcm.js`: float samples to the core's 16-bit PCM.

Used by [connector-slack](../connector-slack/README.md). Each connector depends on it with `"kbma-browser": "file:../connector-browser"`; run `npm ci` here before installing a connector.

```bash
npm ci && npm test
```
