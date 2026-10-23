import assert from "node:assert/strict";
import { test } from "node:test";

import { readOccurrences } from "../src/expand.js";

const calendar = (...events) => ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:test", ...events, "END:VCALENDAR"].join("\r\n");
const event = (lines) => ["BEGIN:VEVENT", ...lines, "END:VEVENT"].join("\r\n");
const window = [new Date("2026-11-01T00:00:00Z"), new Date("2026-11-30T00:00:00Z")];
const legit = event([
  "UID:sync@google.com",
  "DTSTART:20261105T090000Z",
  "DTEND:20261105T093000Z",
  "SUMMARY:Sync",
  "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
]);

test("a rule that never matches is cut off, blocked, and does not starve the others", async () => {
  const never = event([
    "UID:never@evil.example",
    "DTSTART:20200101T090000Z",
    "DTEND:20200101T100000Z",
    "RRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=31",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/zzz-zzzz-zzz",
  ]);
  const blocked = new Set();
  const started = Date.now();
  const found = await readOccurrences(calendar(never, legit), ...window, { agentEmail: "a@x", timeoutMs: 1000, blocked });
  assert.deepEqual(found.map((o) => o.code), ["abc-defg-hij"]);
  assert.ok(found[0].start instanceof Date);
  assert.ok(blocked.has("never@evil.example"));
  assert.ok(Date.now() - started < 8000);
  const again = Date.now();
  await readOccurrences(calendar(never, legit), ...window, { agentEmail: "a@x", timeoutMs: 1000, blocked });
  assert.ok(Date.now() - again < 1000, "a blocked event is not expanded again");
});

test("rules firing several times a day through BYxxx are skipped", async () => {
  const many = event([
    "UID:many@evil.example",
    "DTSTART:19700101T000000Z",
    "DTEND:19700101T000100Z",
    "RRULE:FREQ=DAILY;BYHOUR=0,1,2,3;BYMINUTE=0,1,2,3,4,5;BYSECOND=0,1,2",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/zzz-zzzz-zzz",
  ]);
  const found = await readOccurrences(calendar(many, legit), ...window, { agentEmail: "a@x", timeoutMs: 2000, blocked: new Set() });
  assert.deepEqual(found.map((o) => o.code), ["abc-defg-hij"]);
});

test("any number of never-matching rules are blocked in one read", async () => {
  const traps = Array.from({ length: 6 }, (_, i) => event([
    `UID:trap${i}@evil.example`,
    "DTSTART:20200101T090000Z",
    "DTEND:20200101T100000Z",
    "RRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=31",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/zzz-zzzz-zzz",
  ]));
  const blocked = new Set();
  const found = await readOccurrences(calendar(...traps, legit), ...window, { agentEmail: "a@x", timeoutMs: 300, blocked });
  assert.deepEqual(found.map((o) => o.code), ["abc-defg-hij"]);
  assert.equal(blocked.size, 6);
});

test("a read has a total time budget; the blocked events carry over to the next read", async () => {
  const traps = Array.from({ length: 6 }, (_, i) => event([
    `UID:slow${i}@evil.example`,
    "DTSTART:20200101T090000Z",
    "DTEND:20200101T100000Z",
    "RRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=31",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/zzz-zzzz-zzz",
  ]));
  const blocked = new Set();
  const options = { agentEmail: "a@x", timeoutMs: 300, totalTimeoutMs: 1000, blocked };
  const started = Date.now();
  await assert.rejects(readOccurrences(calendar(...traps, legit), ...window, options), /timed out/);
  assert.ok(Date.now() - started < 2500);
  let found = null;
  for (let read = 0; read < 6 && !found; read++) {
    found = await readOccurrences(calendar(...traps, legit), ...window, options).catch(() => null);
  }
  assert.deepEqual(found.map((o) => o.code), ["abc-defg-hij"]);
});

test("a large calendar is not cut off by the time limit of one recurring event", async () => {
  const many = Array.from({ length: 2_000 }, (_, i) => event([
    `UID:past${i}@google.com`,
    "DTSTART:20200101T090000Z",
    "DTEND:20200101T100000Z",
    `SUMMARY:Past ${i}`,
    "ATTENDEE;PARTSTAT=ACCEPTED:mailto:someone@example.com",
  ]));
  // a per-event limit far shorter than parsing two thousand events
  const found = await readOccurrences(calendar(...many, legit), ...window, { agentEmail: "a@x", timeoutMs: 1, totalTimeoutMs: 20_000 });
  assert.deepEqual(found.map((o) => o.code), ["abc-defg-hij"]);
});
