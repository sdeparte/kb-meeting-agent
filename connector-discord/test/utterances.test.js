import assert from "node:assert/strict";
import { test } from "node:test";

import { UtteranceTracker } from "../src/utterances.js";

test("start, packets and end produce one utterance", () => {
  const tracker = new UtteranceTracker();
  assert.deepEqual(tracker.start("1", 0), [{ type: "utterance_start", t: 0 }]);
  assert.deepEqual(tracker.start("1", 5), []);
  assert.deepEqual(tracker.packet("1", 20), []);
  assert.deepEqual(tracker.end("1", 40), [{ type: "utterance_end", t: 40 }]);
  assert.deepEqual(tracker.end("1", 50), []);
});

test("a packet without start opens an utterance", () => {
  assert.deepEqual(new UtteranceTracker().packet("1", 7), [{ type: "utterance_start", t: 7 }]);
});

test("utterance tracker splits long utterances", () => {
  const tracker = new UtteranceTracker({ maxMs: 1000 });
  tracker.start("1", 0);
  assert.deepEqual(tracker.packet("1", 999), []);
  assert.deepEqual(tracker.packet("1", 1000), [
    { type: "utterance_end", t: 1000 },
    { type: "utterance_start", t: 1000 },
  ]);
});

test("endAll closes every open utterance", () => {
  const tracker = new UtteranceTracker();
  tracker.start("1", 0);
  tracker.start("2", 0);
  assert.deepEqual(tracker.endAll(10).map((e) => e.userId).sort(), ["1", "2"]);
});

test("an utterance ends after a real silence, not at each short pause", () => {
  const tracker = new UtteranceTracker({ silenceMs: 800 });
  tracker.start("1", 0);
  tracker.packet("1", 100);
  assert.deepEqual(tracker.endSilent(500), []); // a 400 ms pause: same utterance
  tracker.packet("1", 600);
  assert.deepEqual(tracker.endSilent(1300), []);
  assert.deepEqual(tracker.endSilent(1420), [{ userId: "1", type: "utterance_end", t: 620 }]);
  assert.deepEqual(tracker.endSilent(5000), []);
});
