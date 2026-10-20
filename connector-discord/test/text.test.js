import assert from "node:assert/strict";
import { test } from "node:test";

import { DISCORD_MESSAGE_LIMIT, isLoggableVoiceDebug, truncate } from "../src/text.js";

test("truncate keeps messages within Discord's limit", () => {
  assert.equal(truncate("short"), "short");
  const long = truncate("x".repeat(5000));
  assert.equal(long.length, DISCORD_MESSAGE_LIMIT);
  assert.ok(long.endsWith("…"));
});

test("voice debug logging keeps DAVE lifecycle lines and drops secrets and packet noise", () => {
  assert.equal(isLoggableVoiceDebug("[NW] [DAVE] Session initialized for protocol version 1"), true);
  assert.equal(isLoggableVoiceDebug("[NW] [DAVE] Transition executed (v1 -> v1, id: 11)"), true);
  assert.equal(
    isLoggableVoiceDebug('[NW] [WS] >> {"op":0,"d":{"token":"redacted","max_dave_protocol_version":1}}'),
    false,
  );
  assert.equal(isLoggableVoiceDebug('[NW] [WS] << {"op":4,"d":{"secret_key":[1,2,3],"dave_protocol_version":1}}'), false);
  assert.equal(isLoggableVoiceDebug('[NW] state change:\nfrom {"dave":{"protocolVersion":1}}'), false);
  assert.equal(isLoggableVoiceDebug("[NW] [DAVE] Failed to decrypt a packet (1 consecutive fails)"), false);
});
