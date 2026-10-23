# connector-browser

A library, not a connector: it is never started on its own. It holds what the connectors that drive a web meeting client in a browser share:

- `browser.js`: launch Chromium (Playwright) on a persistent profile, with fake devices (a microphone that plays silence, its tracks disabled for good, and a camera), and capture the call's audio inside the page, mixed and resampled to 16 kHz;
- `speakers.js`: turn that mixed audio and the platform's "who is speaking" indicator into per-speaker utterances for the core;
- `pcm.js`: float samples to the core's 16-bit PCM;
- `commands.js`: the `!` line of a meeting command the connector types on its own (`!start`, `!fin`), from the catalog the core sends.

Used by [connector-slack](../connector-slack/README.md). Each connector depends on it with `"kbma-browser": "file:../connector-browser"`; run `npm ci` here before installing a connector.

```bash
npm ci && npm test
```
