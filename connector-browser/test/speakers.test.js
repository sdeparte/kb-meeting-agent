import assert from "node:assert/strict";
import { test } from "node:test";

import { SpeakerTracker } from "../src/speakers.js";

const voiced = () => Float32Array.from({ length: 320 }, (_, i) => (i % 2 ? 0.1 : -0.1));
const silent = () => new Float32Array(320);
const names = new Map([["A", "Alice"], ["B", "Bob"]]);

test("the speaker shown speaking gets the audio", () => {
  const tracker = new SpeakerTracker();
  tracker.speaking(["A"], names, 0);
  const { events, frame } = tracker.audio(voiced(), 0);
  assert.deepEqual(events, [{ type: "utterance_start", userId: "A", speakerName: "Alice", t: 0 }]);
  assert.equal(frame.userId, "A");
  assert.equal(frame.pcm.length, 640);
});

test("the one speaking the longest keeps the audio; when they stop it goes to the other", () => {
  const tracker = new SpeakerTracker();
  tracker.speaking(["A"], names, 0);
  tracker.audio(voiced(), 0);
  tracker.speaking(["A", "B"], names, 100);
  assert.equal(tracker.audio(voiced(), 100).frame.userId, "A");
  tracker.speaking(["B"], names, 200);
  const { events, frame } = tracker.audio(voiced(), 200);
  assert.deepEqual(events.map((e) => [e.type, e.userId]), [
    ["utterance_end", "A"],
    ["utterance_start", "B"],
  ]);
  assert.equal(frame.userId, "B");
});

test("voiced audio with nobody shown goes to unknown", () => {
  const tracker = new SpeakerTracker();
  tracker.speaking([], names, 0);
  const { events, frame } = tracker.audio(voiced(), 0);
  assert.deepEqual(events, [{ type: "utterance_start", userId: "unknown", speakerName: "Unknown", t: 0 }]);
  assert.equal(frame.userId, "unknown");
});

test("silence gives no frame and ends the open utterance after silenceMs", () => {
  const tracker = new SpeakerTracker({ silenceMs: 600 });
  tracker.speaking(["A"], names, 0);
  tracker.audio(voiced(), 0);
  tracker.speaking([], names, 20);
  assert.deepEqual(tracker.audio(silent(), 300), { events: [], frame: null });
  const { events, frame } = tracker.audio(silent(), 700);
  assert.equal(frame, null);
  assert.deepEqual(events.map((e) => [e.type, e.userId, e.t]), [["utterance_end", "A", 700]]);
});

test("the agent's own account is never a speaker", () => {
  const tracker = new SpeakerTracker({ selfId: "agent" });
  tracker.speaking(["agent"], names, 0);
  assert.equal(tracker.audio(voiced(), 0).frame.userId, "unknown");
});

test("an opted-out speaker's utterance ends and their audio is dropped", () => {
  const tracker = new SpeakerTracker();
  tracker.speaking(["A"], names, 0);
  tracker.audio(voiced(), 0);
  assert.deepEqual(tracker.optOut("A", 50).map((e) => [e.type, e.userId]), [["utterance_end", "A"]]);
  assert.deepEqual(tracker.audio(voiced(), 60), { events: [], frame: null });
});

test("endAll closes every open utterance", () => {
  const tracker = new SpeakerTracker();
  tracker.speaking(["A"], names, 0);
  tracker.audio(voiced(), 0);
  assert.deepEqual(tracker.endAll(10).map((e) => [e.type, e.userId, e.t]), [["utterance_end", "A", 10]]);
  assert.deepEqual(tracker.endAll(20), []);
});

test("an opted-out speaker talking over someone drops the audio instead of crediting it", () => {
  const tracker = new SpeakerTracker();
  tracker.optOut("A", 0);
  tracker.speaking(["B", "A"], names, 0);
  assert.equal(tracker.audio(voiced(), 10).frame, null);
});

test("audio just after an opted-out speaker stops being shown is dropped, even someone else's", () => {
  const tracker = new SpeakerTracker({ optOutGraceMs: 1000 });
  tracker.optOut("A", 0);
  tracker.speaking(["A"], names, 0);
  tracker.speaking(["B"], names, 100);
  assert.equal(tracker.audio(voiced(), 500).frame, null);
  assert.equal(tracker.audio(voiced(), 1200).frame.userId, "B");
});

test("the grace period runs from when the opted-out speaker stopped being shown", () => {
  const tracker = new SpeakerTracker({ optOutGraceMs: 1000 });
  tracker.speaking(["A"], names, 0); // shown since 0, reported only on changes
  tracker.optOut("A", 3000);
  tracker.speaking(["B"], names, 5000);
  assert.equal(tracker.audio(voiced(), 5500).frame, null);
  assert.equal(tracker.audio(voiced(), 6100).frame.userId, "B");
});

test("once someone opted out, audio nobody is shown speaking is dropped, not unknown", () => {
  const tracker = new SpeakerTracker({ optOutGraceMs: 1000 });
  tracker.optOut("A", 0); // not shown yet: their first words come before the indicator
  tracker.speaking([], names, 0);
  assert.equal(tracker.audio(voiced(), 2000).frame, null);
  tracker.speaking(["B"], names, 2100);
  assert.equal(tracker.audio(voiced(), 2100).frame.userId, "B");
});

test("once someone opted out, a held speaker no longer gets the audio", () => {
  const tracker = new SpeakerTracker({ holdMs: 400 });
  tracker.optOut("A", 0);
  tracker.speaking(["B"], names, 2000);
  tracker.audio(voiced(), 2000);
  tracker.speaking([], names, 2100); // B held until 2500: the voice may be A starting
  assert.equal(tracker.audio(voiced(), 2200).frame, null);
});

test("opting out someone who just stopped being shown starts the grace period", () => {
  const tracker = new SpeakerTracker({ optOutGraceMs: 1000, holdMs: 400 });
  tracker.speaking(["A"], names, 0);
  tracker.speaking(["B"], names, 100); // A held until 500
  tracker.optOut("A", 150);
  assert.equal(tracker.audio(voiced(), 300).frame, null);
  assert.equal(tracker.audio(voiced(), 1200).frame.userId, "B");
});

test("an opt-out repeated on every poll does not extend the grace period", () => {
  const tracker = new SpeakerTracker({ optOutGraceMs: 1000, holdMs: 400 });
  tracker.speaking(["A"], names, 0);
  tracker.optOut("A", 50);
  for (let t = 100; t <= 1100; t += 100) {
    tracker.speaking(["B"], names, t); // A stopped being shown at 100, held until 500
    tracker.optOut("A", t);
  }
  assert.equal(tracker.audio(voiced(), 1150).frame.userId, "B");
});

test("a flickering indicator keeps the speaker's voiced audio for holdMs", () => {
  const tracker = new SpeakerTracker({ holdMs: 400 });
  tracker.speaking(["A"], names, 0);
  tracker.audio(voiced(), 0);
  tracker.speaking([], names, 100); // the indicator drops for a moment
  const held = tracker.audio(voiced(), 200);
  assert.deepEqual(held.events, []);
  assert.equal(held.frame.userId, "A");
  assert.equal(tracker.audio(voiced(), 600).frame.userId, "unknown");
});

test("a held speaker gets no silent audio and gives way to someone shown", () => {
  const tracker = new SpeakerTracker({ holdMs: 400 });
  tracker.speaking(["A"], names, 0);
  tracker.audio(voiced(), 0);
  tracker.speaking([], names, 100);
  assert.equal(tracker.audio(silent(), 150).frame, null);
  tracker.speaking(["B"], names, 200);
  assert.equal(tracker.audio(voiced(), 200).frame.userId, "B");
});
