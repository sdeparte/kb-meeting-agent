import assert from "node:assert/strict";
import { test } from "node:test";

import { MEET_CHAT_MAX, Outbound, chatLine, plainLinks, splitForChat } from "../src/chat.js";

test("a long answer is split under Meet's limit without cutting a word", () => {
  const words = Array.from({ length: 400 }, (_, i) => `mot${i}`);
  const text = words.slice(0, 200).join(" ") + "\n" + words.slice(200).join(" ");
  const parts = splitForChat(text);
  assert.ok(parts.length >= 4);
  assert.ok(parts.every((p) => p.length <= MEET_CHAT_MAX && p.length > 0));
  assert.deepEqual(parts.flatMap((p) => p.split(/\s+/)), words);
});

test("a line break is preferred to a space", () => {
  const text = "a".repeat(300) + "\n" + "b ".repeat(150);
  assert.equal(splitForChat(text)[0], "a".repeat(300));
});

test("a single word longer than the limit is cut", () => {
  assert.deepEqual(splitForChat("x".repeat(700)).map((p) => p.length), [500, 200]);
});

test("Markdown links are written as plain text, the URL in brackets", () => {
  assert.equal(
    plainLinks("See [docs/rules.md](https://github.com/o/kb/blob/main/docs/rules.md#L3) and [x](not a url)."),
    "See docs/rules.md (https://github.com/o/kb/blob/main/docs/rules.md#L3) and [x](not a url).",
  );
});

test("! lines from others go to the core; the agent's own and plain lines do not", () => {
  assert.deepEqual(chatLine({ author: "Alice", text: " !fin ", self: false }), { text: "!fin" });
  assert.equal(chatLine({ author: "Scribe", text: "!fin", self: true }), null);
  assert.equal(chatLine({ author: "Alice", text: "bonjour", self: false }), null);
});

function setup({ fail = false, inMeeting = true, code = "abc-defg-hij" } = {}) {
  const posted = [];
  const toCore = [];
  const ui = {
    sendChat: async (_page, text) => {
      if (fail) throw new Error("chat closed");
      posted.push(text);
    },
  };
  const outbound = new Outbound({ ui, page: {}, currentCode: () => (inMeeting ? code : null), sendToCore: (t, f) => toCore.push([t, f]), log: () => {} });
  return { outbound, posted, toCore };
}

test("the core's messages are posted in parts, in order, then reported sent", async () => {
  const { outbound, posted, toCore } = setup();
  await Promise.all([
    outbound.enqueue({ type: "send", request_id: "r1", text: "y ".repeat(400), buttons: [] }),
    outbound.enqueue({ type: "send", request_id: "r2", text: "second", buttons: [] }),
  ]);
  assert.equal(posted.length, 3);
  assert.equal(posted.at(-1), "second");
  assert.deepEqual(toCore.map(([t, f]) => [t, f.request_id]), [["sent", "r1"], ["sent", "r2"]]);
});

test("a chat failure is reported, not thrown; nothing is posted outside a meeting", async () => {
  const failing = setup({ fail: true });
  await failing.outbound.enqueue({ type: "send", request_id: "r1", text: "x", buttons: [] });
  assert.deepEqual(failing.toCore, [["error", { message: "send: chat closed" }]]);
  const away = setup({ inMeeting: false });
  await away.outbound.enqueue({ type: "send", request_id: "r1", text: "x", buttons: [] });
  assert.deepEqual([away.posted, away.toCore], [[], []]);
});

test("a message for another call is not posted in this one", async () => {
  const { outbound, posted, toCore } = setup();
  await outbound.enqueue({ type: "send", request_id: "r1", channel_id: "xyz-wxyz-xyz", text: "A's answer", buttons: [] });
  assert.deepEqual([posted, toCore], [[], []]);
  await outbound.enqueue({ type: "send", request_id: "r2", channel_id: "abc-defg-hij", text: "ok", buttons: [] });
  assert.deepEqual(posted, ["ok"]);
});
