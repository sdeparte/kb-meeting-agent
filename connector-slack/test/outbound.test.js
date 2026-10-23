import assert from "node:assert/strict";
import { test } from "node:test";

import { Outbound, fitText } from "../src/outbound.js";

function setup({ fail = null, store } = {}) {
  const calls = [];
  const toCore = [];
  let count = 0;
  const client = {
    chat: {
      postMessage: async (args) => {
        calls.push(args);
        if (fail) throw Object.assign(new Error("An API error occurred"), { data: { error: fail } });
        count += 1;
        return { ts: `100.${count}` };
      },
    },
  };
  const outbound = new Outbound({ client, log: () => {}, sendToCore: (type, fields) => toCore.push([type, fields]), store });
  return { outbound, calls, toCore };
}

const send = (text, buttons = [], id = "r1") => ({ type: "send", request_id: id, channel_id: "C1", text, buttons });

test("the first message after a join opens the meeting thread, the next ones answer in it", async () => {
  const { outbound, calls, toCore } = setup();
  await outbound.handle({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await outbound.handle(send("notice"));
  await outbound.handle(send("answer", [], "r2"));
  assert.equal(calls[0].thread_ts, undefined);
  assert.equal(calls[1].thread_ts, "100.1");
  assert.deepEqual(toCore, [
    ["sent", { request_id: "r1", message_id: "100.1" }],
    ["sent", { request_id: "r2", message_id: "100.2" }],
  ]);
});

test("messages after the core leaves (the minutes link) stay in the thread; the next meeting opens its own", async () => {
  const { outbound, calls } = setup();
  await outbound.handle({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await outbound.handle(send("notice"));
  await outbound.handle({ type: "leave" });
  await outbound.handle(send("minutes: https://github.com/o/kb/pull/7", [], "r2"));
  assert.equal(calls[1].thread_ts, "100.1");
  await outbound.handle({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await outbound.handle(send("notice", [], "r3"));
  assert.equal(calls[2].thread_ts, undefined);
});

test("the core's Markdown links become Slack links, and nothing else becomes markup", async () => {
  const { outbound, calls } = setup();
  await outbound.handle(send("`api` [src/a.py#L1-5](https://github.com/o/r/blob/main/src/a.py?x=1&y=2#L1-L5) <!here>"));
  assert.equal(
    calls[0].blocks[0].text.text,
    "`api` <https://github.com/o/r/blob/main/src/a.py?x=1&amp;y=2#L1-L5|src/a.py#L1-5> &lt;!here&gt;",
  );
});

test("buttons become an actions block carrying their ids", async () => {
  const { outbound, calls } = setup();
  await outbound.handle({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  const buttons = [
    { id: "decision:d1:validate", label: "Validate" },
    { id: "decision:d1:edit", label: "Edit", modal: { title: "Edit", label: "Decision", value: "x" } },
  ];
  await outbound.handle(send("Decision detected", buttons));
  const actions = calls[0].blocks.find((b) => b.type === "actions");
  assert.deepEqual(actions.elements.map((e) => [e.action_id, e.style]), [
    ["decision:d1:validate", "primary"],
    ["decision:d1:edit", undefined],
  ]);
  assert.deepEqual(outbound.modals.get("decision:d1:edit"), buttons[1].modal);
});

test("long texts are cut to Slack's limit, with an ellipsis", async () => {
  const { outbound, calls } = setup();
  await outbound.handle(send("x".repeat(5000)));
  assert.equal(calls[0].text.length, 3000);
  assert.ok(calls[0].blocks[0].text.text.endsWith("x…"));
});

test("a cut never splits an entity or a link", () => {
  assert.equal(fitText("abcd&amp;", 7), "abcd…");
  assert.equal(fitText("ab <https://x.y/z|label> cd", 12), "ab …");
  assert.equal(fitText("short", 7), "short");
});

test("a restarted connector goes on answering in the meeting's thread", async () => {
  let saved = null;
  const store = { load: () => saved, save: (state) => (saved = state) };
  const first = setup({ store });
  await first.outbound.handle({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await first.outbound.handle(send("notice"));
  const restarted = setup({ store });
  await restarted.outbound.handle({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await restarted.outbound.handle(send("audio interrupted"));
  assert.equal(restarted.calls[0].thread_ts, "100.1");
});

test("a Slack API error is reported to the core, never thrown", async () => {
  const { outbound, toCore } = setup({ fail: "channel_not_found" });
  await outbound.handle(send("hello"));
  assert.deepEqual(toCore, [["error", { message: "send: channel_not_found" }]]);
});

test("modals given back after a restart are remembered; replies are ignored", async () => {
  const { outbound, calls } = setup();
  await outbound.handle({ type: "modals", modals: [{ id: "decision:d2:edit", modal: { title: "t", label: "l", value: "v" } }] });
  await outbound.handle({ type: "reply", interaction_id: "i1", text: "x" });
  assert.equal(outbound.modals.get("decision:d2:edit").value, "v");
  assert.equal(calls.length, 0);
});

test("texts never mention anyone: Slack's markup characters are escaped", async () => {
  const { outbound, calls } = setup();
  await outbound.handle(send("Bob said <!channel> & <@U123> > all"));
  const expected = "Bob said &lt;!channel&gt; &amp; &lt;@U123&gt; &gt; all";
  assert.equal(calls[0].text, expected);
  assert.equal(calls[0].blocks[0].text.text, expected);
});

test("messages sent back to back share one thread root", async () => {
  const calls = [];
  const toCore = [];
  let count = 0;
  const client = {
    chat: {
      postMessage: async (args) => {
        calls.push(args);
        count += 1;
        const ts = `200.${count}`;
        await new Promise((resolve) => setTimeout(resolve, count === 1 ? 30 : 0)); // the first is slower
        return { ts };
      },
    },
  };
  const outbound = new Outbound({ client, log: () => {}, sendToCore: (t, f) => toCore.push([t, f]) });
  await outbound.enqueue({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await Promise.all([outbound.enqueue(send("notice")), outbound.enqueue(send("started", [], "r2"))]);
  assert.equal(calls[0].thread_ts, undefined);
  assert.equal(calls[1].thread_ts, "200.1");
});

test("a repeated join on the same channel keeps the thread", async () => {
  const { outbound, calls } = setup();
  const join = { type: "join", voice_channel_id: "C1", text_channel_id: "C1" };
  await outbound.handle(join);
  await outbound.handle(send("notice"));
  await outbound.handle(join);
  await outbound.handle(send("later", [], "r2"));
  assert.equal(calls[1].thread_ts, "100.1");
});
