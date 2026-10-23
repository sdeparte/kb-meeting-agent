import assert from "node:assert/strict";
import { test } from "node:test";

import { Schedule } from "../src/schedule.js";

const NOW = Date.parse("2026-11-05T08:59:30Z");
const ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:test", "BEGIN:VEVENT", "UID:sync@google.com",
  "DTSTART:20261105T090000Z", "DTEND:20261105T093000Z", "SUMMARY:Sync",
  "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij", "END:VEVENT", "END:VCALENDAR"].join("\r\n");

function setup({ fetches, handled = () => false, leftAt = () => null }) {
  const logs = [];
  const schedule = new Schedule({
    fetchCalendar: async () => {
      const next = fetches.shift();
      if (next instanceof Error) throw next;
      return next;
    },
    agentEmail: "scribe@example.com",
    handled: { has: handled, leftAt },
    joinEarlyMs: 60_000,
    log: (line) => logs.push(line),
    clock: () => NOW,
  });
  return { schedule, logs };
}

test("the meeting due now is returned", async () => {
  const { schedule } = setup({ fetches: [ics] });
  assert.equal((await schedule.next()).code, "abc-defg-hij");
});

test("a handled occurrence is skipped", async () => {
  const { schedule } = setup({ fetches: [ics], handled: () => true });
  assert.equal(await schedule.next(), null);
});

test("a call left on purpose is not joined again under another key, until a later occurrence", async () => {
  // left after a rejoin, which marks the call's code, not the calendar occurrence's key
  const left = setup({ fetches: [ics], leftAt: (code) => (code === "abc-defg-hij" ? NOW - 1_000 : null) });
  assert.equal(await left.schedule.next(), null);
  // left before this occurrence could be joined (the same call, last week): joined
  const earlier = setup({ fetches: [ics], leftAt: () => Date.parse("2026-11-05T08:58:00Z") });
  assert.equal((await earlier.schedule.next()).code, "abc-defg-hij");
});

test("fetch failures are logged once per streak, without the calendar address", async () => {
  const secret = "https://calendar.google.com/calendar/ical/scribe%40example.com/private-0123abcd/basic.ics";
  const failure = new Error(`fetch failed for ${secret}`);
  const { schedule, logs } = setup({ fetches: [failure, new Error(`404 ${secret}`), ics, failure] });
  assert.equal(await schedule.next(), null);
  assert.equal(await schedule.next(), null);
  assert.equal(logs.length, 1);
  assert.ok(!logs.join("\n").includes("calendar.google.com"));
  assert.ok(!logs.join("\n").includes("private-0123abcd"));
  assert.equal((await schedule.next()).code, "abc-defg-hij");
  await schedule.next();
  assert.equal(logs.length, 2);
});
