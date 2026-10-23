import assert from "node:assert/strict";
import { test } from "node:test";

import { CommandLines } from "kbma-browser/commands";
import { SpeakerTracker } from "kbma-browser/speakers";

import { Meeting } from "../src/meeting.js";

const voiced = () => Float32Array.from({ length: 320 }, (_, i) => (i % 2 ? 0.1 : -0.1));
const OCCURRENCE = { key: "w@1", summary: "Weekly", code: "abc-defg-hij", url: "https://meet.google.com/abc-defg-hij", start: new Date(0), end: new Date(3_600_000) };

const CATALOG = [
  { id: "meeting_start", words: ["start"], slash: ["meeting", "start"] },
  { id: "meeting_end", words: ["fin", "end"], slash: ["meeting", "end"] },
];

function setup({ admission = ["in"], catalog = CATALOG } = {}) {
  let now = 0;
  const commands = new CommandLines();
  if (catalog) commands.setCatalog(catalog);
  const calls = [];
  const ui = {
    present: true,
    over: false,
    people: [{ id: "p-self", name: "Scribe", self: true }, { id: "p1", name: "Alice", self: false }],
    speaking: [],
    lines: [],
    count: null,
    open: async (_page, url) => calls.push(["open", url]),
    abandon: async () => calls.push(["abandon"]),
    participantCount: async () => ui.count,
    prepare: async () => calls.push(["prepare"]),
    askToJoin: async () => (admission[0] === "in" ? "joined" : "waiting"),
    admitted: async () => admission.shift() ?? "waiting",
    inMeeting: async () => ui.present,
    ended: async () => ui.over,
    leave: async () => calls.push(["leave"]),
    participants: async () => ui.people,
    speakers: async () => ui.speaking,
    readChat: async () => ui.lines.splice(0),
  };
  const marked = [];
  const toCore = [];
  const audio = [];
  const logs = [];
  const meeting = new Meeting({
    ui,
    page: {},
    makeTracker: (selfId) => new SpeakerTracker({ selfId }),
    handled: { mark: (key) => marked.push(key) },
    commands,
    sendToCore: (type, fields) => toCore.push([type, fields]),
    sendAudio: (userId, t, pcm) => audio.push([userId, t, pcm.length]),
    log: (line) => logs.push(line),
    clock: () => now,
    sleep: async (ms) => { now += ms; },
    admissionTimeoutMs: 10_000,
    missesToLeave: 3,
    endsToLeave: 2,
  });
  const of = (type) => toCore.filter(([t]) => t === type).map(([, f]) => f);
  return { meeting, ui, calls, marked, toCore, audio, logs, of, commands, tick: (ms) => { now += ms; } };
}

test("admitted at once: ready, members, and the meeting starts on the Meet code", async () => {
  const { meeting, calls, of } = setup();
  assert.equal(await meeting.join(OCCURRENCE), true);
  assert.deepEqual(calls.slice(0, 2), [["open", OCCURRENCE.url], ["prepare"]]);
  assert.deepEqual(of("voice_state"), [{ status: "ready" }]);
  assert.deepEqual(of("members")[0].members, [
    { id: "p-self", name: "Scribe", bot: true },
    { id: "p1", name: "Alice", bot: false },
  ]);
  assert.deepEqual(of("chat"), [
    { text: "!start", user: { id: "calendar", name: "Calendar" }, text_channel_id: "abc-defg-hij", voice_channel_id: "abc-defg-hij" },
  ]);
  assert.equal(meeting.current, OCCURRENCE);
});

test("admitted after waiting in the lobby: the meeting starts", async () => {
  const { meeting, of } = setup({ admission: ["waiting", "waiting", "in"] });
  assert.equal(await meeting.join(OCCURRENCE), true);
  assert.equal(of("chat").length, 1);
});

test("never admitted, or refused: given up, marked, no meeting", async () => {
  for (const admission of [["waiting"], ["waiting", "refused"]]) {
    const { meeting, marked, of, logs } = setup({ admission });
    assert.equal(await meeting.join(OCCURRENCE), false);
    assert.deepEqual(marked, ["w@1", "left@abc-defg-hij"]);
    assert.deepEqual(of("chat"), []);
    assert.equal(meeting.current, null);
    assert.match(logs.at(-1), /not admitted to Weekly \(abc-defg-hij\)/);
  }
});

test("the call ending for everyone ends the meeting and marks it", async () => {
  const { meeting, ui, marked, of } = setup();
  await meeting.join(OCCURRENCE);
  ui.present = false;
  ui.over = true;
  await meeting.poll(100);
  await meeting.poll(200);
  assert.equal(of("chat").at(-1).text, "!end");
  assert.deepEqual(marked, ["w@1", "left@abc-defg-hij"]);
  assert.equal(meeting.current, null);
});

test("leave from the core leaves Meet, marks the occurrence, and sends no !fin", async () => {
  const { meeting, calls, marked, of } = setup();
  await meeting.join(OCCURRENCE);
  await meeting.onCore({ type: "leave" });
  assert.deepEqual(calls.at(-1), ["leave"]);
  assert.deepEqual(marked, ["w@1", "left@abc-defg-hij"]);
  assert.ok(!of("chat").some((f) => f.text === "!end"));
  assert.equal(meeting.current, null);
});

test("! lines from participants go to the core; the agent's own do not", async () => {
  const { meeting, ui, of } = setup();
  await meeting.join(OCCURRENCE);
  ui.lines.push({ author: "Alice", text: "!ask cooldown ?", self: false }, { author: "Scribe", text: "!ask echo", self: true });
  await meeting.poll(100);
  assert.deepEqual(of("chat").slice(1), [
    { text: "!ask cooldown ?", user: { id: "p1", name: "Alice" }, text_channel_id: "abc-defg-hij", voice_channel_id: "abc-defg-hij" },
  ]);
});

test("the speaker shown gets the audio; the agent's own tile never does", async () => {
  const { meeting, ui, audio } = setup();
  await meeting.join(OCCURRENCE);
  ui.speaking = ["p-self"];
  await meeting.poll(100);
  meeting.onSamples(voiced(), 100);
  assert.equal(audio[0][0], "unknown");
  ui.speaking = ["p1"];
  await meeting.poll(200);
  meeting.onSamples(voiced(), 200);
  assert.equal(audio.at(-1)[0], "p1");
});

test("two participants with the same name stay two members", async () => {
  const { meeting, ui, of } = setup();
  ui.people = [...ui.people, { id: "p2", name: "Alex", self: false }, { id: "p3", name: "Alex", self: false }];
  await meeting.join(OCCURRENCE);
  assert.equal(of("members")[0].members.filter((m) => m.name === "Alex").length, 2);
});

test("the core's join for the current meeting is answered ready", async () => {
  const { meeting, of } = setup();
  await meeting.join(OCCURRENCE);
  await meeting.onCore({ type: "join", voice_channel_id: "abc-defg-hij", text_channel_id: "abc-defg-hij" });
  assert.equal(of("voice_state").length, 2);
});

test("a chat command carries the author's participant id, so !optout reaches their audio", async () => {
  const { meeting, ui, audio, of } = setup();
  await meeting.join(OCCURRENCE);
  ui.lines.push({ author: "Alice", text: "!optout", self: false });
  await meeting.poll(100);
  const optout = of("chat").at(-1);
  assert.equal(optout.user.id, "p1");
  await meeting.onCore({ type: "optout", user_id: optout.user.id });
  ui.speaking = ["p1"];
  await meeting.poll(200);
  meeting.onSamples(voiced(), 200);
  assert.deepEqual(audio, []);
});

test("an opt-out by an ambiguous name covers every participant of that name", async () => {
  const { meeting, ui, audio, of } = setup();
  ui.people = [...ui.people, { id: "p2", name: "Alex", self: false }, { id: "p3", name: "Alex", self: false }];
  await meeting.join(OCCURRENCE);
  ui.lines.push({ author: "Alex", text: "!optout", self: false });
  await meeting.poll(100);
  const optout = of("chat").at(-1);
  assert.deepEqual(optout.user, { id: "Alex", name: "Alex", speaker_ids: ["p2", "p3"] });
  await meeting.onCore({ type: "optout", user_id: optout.user.id });
  for (const id of ["p2", "p3"]) {
    ui.speaking = [id];
    await meeting.poll(5000);
    meeting.onSamples(voiced(), 5000);
  }
  assert.deepEqual(audio, []);
});

const join = (code = "abc-defg-hij") => ({ type: "join", voice_channel_id: code, text_channel_id: code });
const OTHER = { ...OCCURRENCE, key: "o@1", summary: "Other", code: "xyz-wxyz-xyz", url: "https://meet.google.com/xyz-wxyz-xyz" };

test("the core's meeting is the one wanted: rejoined from its code, ready, without a new start", async () => {
  const { meeting, calls, of } = setup();
  await meeting.onCore(join());
  assert.equal(meeting.wanted, "abc-defg-hij");
  assert.equal(await meeting.rejoin(), true);
  assert.deepEqual(calls[0], ["open", "https://meet.google.com/abc-defg-hij"]);
  assert.deepEqual(of("voice_state"), [{ status: "ready" }]);
  assert.deepEqual(of("chat"), []);
});

test("another meeting is not joined while the core's meeting is wanted", async () => {
  const { meeting, calls, audio, of } = setup();
  await meeting.onCore(join());
  assert.equal(await meeting.join(OTHER), false);
  assert.deepEqual(calls, []);
  meeting.onSamples(voiced(), 0);
  assert.deepEqual([audio, of("voice_state")], [[], []]);
});

test("giving up on the wanted meeting asks the core to end it, and leaves the lobby", async () => {
  const { meeting, calls, of } = setup({ admission: ["waiting"] });
  await meeting.onCore(join());
  assert.equal(await meeting.rejoin(), false);
  assert.deepEqual(calls.at(-1), ["abandon"]);
  assert.deepEqual(of("chat").at(-1), {
    text: "!end",
    user: { id: "calendar", name: "Calendar" },
    text_channel_id: "abc-defg-hij",
    voice_channel_id: "abc-defg-hij",
  });
});

test("not admitted to a calendar meeting: the lobby is left too", async () => {
  const { meeting, calls } = setup({ admission: ["waiting", "refused"] });
  await meeting.join(OCCURRENCE);
  assert.deepEqual(calls.at(-1), ["abandon"]);
});

test("opt-outs sent before the agent is back in the call apply once it is", async () => {
  const { meeting, ui, audio } = setup();
  await meeting.onCore(join());
  await meeting.onCore({ type: "optout", user_id: "p1" });
  await meeting.rejoin();
  ui.speaking = ["p1"];
  await meeting.poll(100);
  meeting.onSamples(voiced(), 100);
  assert.deepEqual(audio, []);
});

test("an opt-out by name follows that person when they come back with a new id", async () => {
  const { meeting, ui, audio } = setup();
  ui.people = [...ui.people, { id: "p2", name: "Alex", self: false }, { id: "p3", name: "Alex", self: false }];
  await meeting.join(OCCURRENCE);
  await meeting.onCore({ type: "optout", user_id: "Alex" });
  ui.people = [ui.people[0], ui.people[1], { id: "p9", name: "Alex", self: false }];
  ui.speaking = ["p9"];
  await meeting.poll(5000);
  meeting.onSamples(voiced(), 5000);
  assert.deepEqual(audio, []);
});

test("an 'ended' phrase seen while still in the call ends nothing", async () => {
  const { meeting, ui, marked, of } = setup();
  await meeting.join(OCCURRENCE);
  ui.over = true; // e.g. someone typed "you left the meeting" in the chat
  await meeting.poll(100);
  assert.deepEqual(marked, []);
  assert.equal(of("chat").length, 1);
});

test("dropping out of the call is not the end: voice lost, not marked, rejoined", async () => {
  const { meeting, ui, marked, of } = setup();
  await meeting.onCore(join()); // the core's meeting
  await meeting.join(OCCURRENCE);
  ui.present = false;
  for (const t of [100, 200, 300]) await meeting.poll(t);
  assert.deepEqual(of("voice_state").at(-1), { status: "lost" });
  assert.deepEqual(marked, []);
  assert.ok(!of("chat").some((f) => f.text === "!end"));
  assert.equal(meeting.current, null);
  ui.present = true;
  assert.equal(await meeting.rejoin(), true);
});

test("members: everyone seen in the tiles, and only the agent once Meet counts one person", async () => {
  const { meeting, ui, of } = setup();
  await meeting.join(OCCURRENCE);
  ui.people = [ui.people[0]]; // a screen share hides Alice's tile
  for (let t = 0; t < 10; t++) await meeting.poll(t * 100);
  assert.deepEqual(of("members").at(-1).members.map((m) => m.id), ["p-self", "p1"]);
  ui.count = 1;
  for (let t = 10; t < 20; t++) await meeting.poll(t * 100);
  assert.deepEqual(of("members").at(-1).members.map((m) => m.id), ["p-self"]);
});

test("the end screen seen once ends nothing: its words can be typed in the chat", async () => {
  const { meeting, ui, marked, of } = setup();
  await meeting.join(OCCURRENCE);
  ui.present = false; // a re-render hides the Leave button for one poll
  ui.over = true;
  await meeting.poll(100);
  ui.present = true;
  await meeting.poll(200);
  assert.deepEqual(marked, []);
  assert.ok(!of("chat").some((f) => f.text === "!end"));
  assert.equal(meeting.current, OCCURRENCE);
});

test("a call left on purpose after a rejoin is remembered by its code", async () => {
  const { meeting, ui, marked } = setup();
  await meeting.onCore(join());
  await meeting.join(OCCURRENCE);
  ui.present = false;
  for (const t of [100, 200, 300]) await meeting.poll(t); // dropped
  ui.present = true;
  await meeting.rejoin();
  await meeting.onCore({ type: "leave" }); // !fin typed after the rejoin
  assert.deepEqual(marked, ["core@abc-defg-hij", "left@abc-defg-hij"]);
});

test("the core's meeting closed during a rejoin's admission: the call is left, no new start", async () => {
  const { meeting, ui, calls, of } = setup({ admission: ["waiting", "in"] });
  await meeting.onCore(join());
  ui.admitted = async () => {
    await meeting.onCore({ type: "leave" }); // e.g. the core's auto-leave, while in the lobby
    return "in";
  };
  assert.equal(await meeting.rejoin(), false);
  assert.deepEqual(calls.at(-1), ["leave"]);
  assert.deepEqual([of("chat"), of("voice_state"), of("members")], [[], [], []]);
  assert.equal(meeting.current, null);
});

test("the core names its meeting while a calendar one is being joined: that call is left", async () => {
  const { meeting, ui, calls, marked, of } = setup({ admission: ["waiting", "in"] });
  ui.admitted = async () => {
    await meeting.onCore(join(OTHER.code)); // a restarted connector: the core resumes its meeting
    return "in";
  };
  assert.equal(await meeting.join(OCCURRENCE), false);
  assert.deepEqual(calls.at(-1), ["leave"]);
  assert.deepEqual([of("chat"), of("voice_state"), of("members"), marked], [[], [], [], []]);
});

test("the core names another meeting while in a calendar one: the call is left, its chat no longer read", async () => {
  const { meeting, ui, calls, of } = setup();
  await meeting.join(OCCURRENCE);
  await meeting.onCore(join(OTHER.code));
  assert.deepEqual(calls.at(-1), ["leave"]);
  assert.equal(meeting.current, null);
  ui.lines.push({ author: "Alice", text: "!fin", self: false });
  await meeting.poll(100);
  assert.equal(of("chat").length, 1); // the !start only
});

test("a rejoin that keeps failing ends the core's meeting after the admission time", async () => {
  const { meeting, ui, marked, of, tick } = setup();
  await meeting.onCore(join());
  ui.askToJoin = async () => {
    throw new Error("no join button");
  };
  await assert.rejects(meeting.rejoin(), /no join button/);
  tick(5_000);
  await assert.rejects(meeting.rejoin(), /no join button/);
  assert.deepEqual(of("chat"), []);
  tick(5_000); // the admission timeout (10 s) since the first failure
  assert.equal(await meeting.rejoin(), false);
  assert.deepEqual(of("chat").map((f) => f.text), ["!end"]);
  assert.ok(marked.includes("left@abc-defg-hij"));
});

test("an opt-out by participant id follows that person when they come back with a new id", async () => {
  const { meeting, ui, audio } = setup();
  await meeting.join(OCCURRENCE);
  await meeting.onCore({ type: "optout", user_id: "p1" });
  ui.people = [ui.people[0], { id: "p7", name: "Alice", self: false }]; // Alice reconnected
  ui.speaking = ["p7"];
  await meeting.poll(5000);
  meeting.onSamples(voiced(), 5000);
  assert.deepEqual(audio, []);
});

test("a meeting joined before the core's catalog arrived starts once it does", async () => {
  const { meeting, of, commands } = setup({ catalog: null });
  await meeting.join(OCCURRENCE);
  assert.deepEqual(of("chat"), []);
  commands.setCatalog(CATALOG);
  assert.deepEqual(of("chat").map((f) => f.text), ["!start"]);
});
