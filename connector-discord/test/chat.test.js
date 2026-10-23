import assert from "node:assert/strict";
import { test } from "node:test";

import { isCommandForCore } from "../src/chat.js";

function message({ content = "!end", bot = false, guildId = "g1", channelId = "c1", voice = false } = {}) {
  return { content, author: { bot }, guildId, channelId, channel: { isVoiceBased: () => voice } };
}

const where = { guildId: "g1", meetingTextChannelId: "meeting-text" };

test("! lines in a voice channel's chat go to the core", () => {
  assert.equal(isCommandForCore(message({ voice: true }), where), true);
});

test("! lines in the meeting's text channel go to the core", () => {
  assert.equal(isCommandForCore(message({ channelId: "meeting-text" }), where), true);
});

test("other channels, other servers, bots and plain lines do not", () => {
  assert.equal(isCommandForCore(message({ channelId: "music" }), where), false);
  assert.equal(isCommandForCore(message({ voice: true, guildId: "g2" }), where), false);
  assert.equal(isCommandForCore(message({ voice: true, bot: true }), where), false);
  assert.equal(isCommandForCore(message({ voice: true, content: "hello" }), where), false);
  assert.equal(isCommandForCore(message({ channelId: "music" }), { guildId: "g1", meetingTextChannelId: null }), false);
});
