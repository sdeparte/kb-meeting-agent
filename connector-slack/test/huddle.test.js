import assert from "node:assert/strict";
import { test } from "node:test";

import { CommandLines } from "kbma-browser/commands";
import { SpeakerTracker } from "kbma-browser/speakers";

import { Huddle } from "../src/huddle.js";

const voiced = () => Float32Array.from({ length: 320 }, (_, i) => (i % 2 ? 0.1 : -0.1));
const CATALOG = [{ id: "meeting_start", words: ["start"], slash: ["meeting", "start"] }];

function setup({ channel = "C1", catalog = CATALOG } = {}) {
  const commands = new CommandLines();
  if (catalog) commands.setCatalog(catalog);
  const calls = [];
  const ui = {
    speaking: [],
    people: [{ id: "UAGENT", name: "Scribe" }, { id: "U1", name: "Alice" }],
    present: false,
    waitForInvite: async () => ({}),
    join: async () => { calls.push("join"); ui.present = true; },
    leave: async () => { calls.push("leave"); ui.present = false; },
    speakers: async () => ui.speaking,
    participants: async () => ui.people,
    inHuddle: async () => ui.present,
  };
  const toCore = [];
  const audio = [];
  const logs = [];
  const huddle = new Huddle({
    ui,
    page: {},
    makeTracker: () => new SpeakerTracker({ selfId: "UAGENT" }),
    agentUserId: "UAGENT",
    channelOf: async (meetingChannel) => (typeof channel === "function" ? channel(meetingChannel) : channel),
    nameOf: (id) => ({ U1: "Alice" })[id] ?? id,
    commands,
    sendToCore: (type, fields) => toCore.push([type, fields]),
    sendAudio: (userId, t, pcm) => audio.push([userId, t, pcm.length]),
    log: (line) => logs.push(line),
    missesToLeave: 3,
  });
  const of = (type) => toCore.filter(([t]) => t === type).map(([, f]) => f);
  return { huddle, ui, calls, toCore, audio, logs, of, commands };
}

test("an invitation joins, reports the voice ready and the members, and starts the meeting", async () => {
  const { huddle, calls, of } = setup();
  await huddle.acceptInvite();
  assert.deepEqual(calls, ["join"]);
  assert.deepEqual(of("voice_state"), [{ status: "ready" }]);
  assert.deepEqual(of("members").at(-1).members, [
    { id: "UAGENT", name: "Scribe", bot: true },
    { id: "U1", name: "Alice", bot: false },
  ]);
  assert.deepEqual(of("chat"), [
    { text: "!start", user: { id: "UAGENT", name: "Slack" }, text_channel_id: "C1", voice_channel_id: "C1" },
  ]);
});

test("an invitation before the core's catalog starts the meeting once the catalog arrives", async () => {
  const { huddle, of, commands } = setup({ catalog: null });
  await huddle.acceptInvite();
  assert.deepEqual(of("chat"), []);
  commands.setCatalog(CATALOG);
  assert.deepEqual(of("chat").map((f) => [f.text, f.text_channel_id]), [["!start", "C1"]]);
});

test("the core's join on the huddle's channel is answered ready, not by a new start", async () => {
  const { huddle, of } = setup();
  await huddle.acceptInvite();
  await huddle.onCore({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  assert.equal(of("voice_state").length, 2);
  assert.equal(of("chat").length, 1);
});

test("re-invited after a restart into the meeting's channel: ready, no second start", async () => {
  const asked = [];
  // the huddle's thread message predates the restart: found in the meeting's channel
  const { huddle, of } = setup({ channel: (meetingChannel) => (asked.push(meetingChannel), "C1") });
  await huddle.onCore({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await huddle.onCore({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" }); // the core repeats it
  assert.deepEqual(of("voice_state"), [{ status: "needs_invite" }]);
  await huddle.acceptInvite();
  assert.deepEqual(asked, ["C1"]);
  assert.deepEqual(of("voice_state").at(-1), { status: "ready" });
  assert.deepEqual(of("chat"), []);
});

test("while a meeting runs, a huddle whose channel cannot be confirmed is left, never recorded", async () => {
  const { huddle, ui, calls, audio, of } = setup({ channel: null });
  await huddle.onCore({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await huddle.acceptInvite();
  assert.deepEqual(calls, ["join", "leave"]);
  ui.speaking = ["U1"];
  await huddle.poll(0);
  huddle.onSamples(voiced(), 0);
  assert.deepEqual(audio, []);
  assert.ok(!of("voice_state").some((f) => f.status === "ready"));
});

test("a huddle in another channel than the running meeting is left, and never recorded", async () => {
  const { huddle, ui, calls, audio, of } = setup({ channel: "C2" });
  await huddle.onCore({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await huddle.acceptInvite();
  assert.deepEqual(calls, ["join", "leave"]);
  ui.speaking = ["U1"];
  await huddle.poll(0);
  huddle.onSamples(voiced(), 0);
  assert.deepEqual(audio, []);
  assert.deepEqual(of("chat"), []);
});

test("a huddle whose channel is unknown is left", async () => {
  const { huddle, calls, logs } = setup({ channel: null });
  await huddle.acceptInvite();
  assert.deepEqual(calls, ["join", "leave"]);
  assert.match(logs.at(-1), /channel is unknown/);
});

test("a second invitation while in a huddle is ignored", async () => {
  const { huddle, calls, logs } = setup();
  await huddle.acceptInvite();
  await huddle.acceptInvite();
  assert.deepEqual(calls, ["join"]);
  assert.match(logs.at(-1), /ignoring a huddle invitation: already in one/);
});

test("the speaker shown by the UI gets the audio", async () => {
  const { huddle, ui, toCore, audio } = setup();
  await huddle.acceptInvite();
  ui.speaking = ["U1"];
  await huddle.poll(1000);
  huddle.onSamples(voiced(), 1000);
  assert.deepEqual(toCore.at(-1), ["utterance_start", { user_id: "U1", speaker_name: "Alice", t: 1000 }]);
  assert.deepEqual(audio, [["U1", 1000, 640]]);
});

test("audio before joining is not sent", () => {
  const { huddle, audio } = setup();
  huddle.onSamples(voiced(), 0);
  assert.deepEqual(audio, []);
});

test("leave from the core leaves the huddle and ends the utterances", async () => {
  const { huddle, ui, calls, toCore, audio, of } = setup();
  await huddle.acceptInvite();
  ui.speaking = ["U1"];
  await huddle.poll(0);
  huddle.onSamples(voiced(), 0);
  await huddle.onCore({ type: "leave" });
  assert.deepEqual(calls, ["join", "leave"]);
  assert.equal(toCore.at(-1)[0], "utterance_end");
  huddle.onSamples(voiced(), 50);
  assert.equal(audio.length, 1);
  for (let t = 100; t < 600; t += 100) await huddle.poll(t);
  assert.ok(!of("chat").some((f) => f.text === "!fin"));
});

test("one missed poll is nothing; staying out of the huddle loses the voice, never ends the meeting", async () => {
  const { huddle, ui, of } = setup();
  await huddle.acceptInvite();
  await huddle.onCore({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  ui.present = false;
  await huddle.poll(100);
  ui.present = true;
  await huddle.poll(200);
  ui.present = false;
  for (const t of [300, 400]) await huddle.poll(t);
  assert.notDeepEqual(of("voice_state").at(-1), { status: "needs_invite" });
  await huddle.poll(500);
  assert.deepEqual(of("voice_state").at(-1), { status: "needs_invite" });
  assert.deepEqual(of("members").at(-1), { members: [] }); // the core's auto-leave takes over
  assert.deepEqual(of("chat").map((f) => f.text), ["!start"]);
  await huddle.acceptInvite(); // invited again: back in the meeting
  assert.deepEqual(of("voice_state").at(-1), { status: "ready" });
  assert.equal(of("members").at(-1).members.length, 2);
});

test("out of a huddle no meeting was started in, nothing is reported", async () => {
  const { huddle, ui, toCore } = setup({ catalog: null }); // the start never went out
  await huddle.acceptInvite();
  const sent = toCore.length;
  ui.present = false;
  for (const t of [100, 200, 300]) await huddle.poll(t);
  assert.equal(toCore.length, sent);
});

test("an opt-out does not carry over to the next huddle", async () => {
  const { huddle, ui, audio } = setup();
  await huddle.acceptInvite();
  await huddle.onCore({ type: "optout", user_id: "U1" });
  ui.speaking = ["U1"];
  await huddle.poll(0);
  huddle.onSamples(voiced(), 0);
  assert.deepEqual(audio, []);
  await huddle.onCore({ type: "leave" });
  await huddle.acceptInvite();
  await huddle.poll(5000);
  huddle.onSamples(voiced(), 5000);
  assert.equal(audio.at(-1)[0], "U1");
});

test("opt-outs the core re-sends after a restart apply once the account is invited back", async () => {
  const { huddle, ui, audio } = setup();
  await huddle.onCore({ type: "join", voice_channel_id: "C1", text_channel_id: "C1" });
  await huddle.onCore({ type: "optout", user_id: "U1" }); // no huddle yet: kept
  await huddle.acceptInvite();
  ui.speaking = ["U1"];
  await huddle.poll(0);
  huddle.onSamples(voiced(), 0);
  ui.speaking = [];
  await huddle.poll(5000);
  huddle.onSamples(voiced(), 5000); // nobody shown: could be them starting to speak
  assert.deepEqual(audio, []);
});

test("a speaker is named from the huddle's tiles from their first utterance", async () => {
  const { huddle, ui, toCore } = setup();
  await huddle.acceptInvite();
  ui.people = [...ui.people, { id: "U2", name: "Bob" }]; // joined after the last members report
  ui.speaking = ["U2"];
  await huddle.poll(100);
  huddle.onSamples(voiced(), 100);
  assert.deepEqual(toCore.at(-1), ["utterance_start", { user_id: "U2", speaker_name: "Bob", t: 100 }]);
});

test("chat lines carry the huddle as their voice channel only from the huddle's channel", async () => {
  const { huddle } = setup();
  await huddle.acceptInvite();
  assert.equal(huddle.voiceFor("C1"), "C1");
  assert.equal(huddle.voiceFor("C9"), null);
});
