import assert from "node:assert/strict";
import { test } from "node:test";

import { dueMeeting, occurrences } from "../src/calendar.js";

const PARIS = `BEGIN:VTIMEZONE
TZID:Europe/Paris
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE`;

const calendar = (...events) =>
  ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:test", PARIS, ...events, "END:VCALENDAR"].join("\r\n");

const event = (lines) => ["BEGIN:VEVENT", ...lines, "END:VEVENT"].join("\r\n");
const AGENT = "scribe@example.com";
const window = [new Date("2026-11-01T00:00:00Z"), new Date("2026-11-30T00:00:00Z")];
const find = (ics) => occurrences(ics, ...window, { agentEmail: AGENT });

const weekly = [
  "UID:weekly@google.com",
  "DTSTART;TZID=Europe/Paris:20261102T100000",
  "DTEND;TZID=Europe/Paris:20261102T110000",
  "RRULE:FREQ=WEEKLY;COUNT=3",
  "SUMMARY:Weekly",
  "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
];

test("an event with a Meet link is an occurrence with its code", () => {
  const [one] = find(calendar(event([
    "UID:one@google.com",
    "DTSTART:20261105T090000Z",
    "DTEND:20261105T093000Z",
    "SUMMARY:Sync",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
  ])));
  assert.equal(one.code, "abc-defg-hij");
  assert.equal(one.url, "https://meet.google.com/abc-defg-hij");
  assert.equal(one.summary, "Sync");
  assert.equal(one.start.toISOString(), "2026-11-05T09:00:00.000Z");
  assert.equal(one.end.toISOString(), "2026-11-05T09:30:00.000Z");
});

test("a Meet link in the description counts; no link, cancelled or declined by the agent do not", () => {
  const base = ["DTSTART:20261105T090000Z", "DTEND:20261105T093000Z", "SUMMARY:x"];
  const ics = calendar(
    event(["UID:a@google.com", ...base, "DESCRIPTION:Join: https://meet.google.com/aaa-bbbb-ccc"]),
    event(["UID:b@google.com", ...base, "LOCATION:Room 1"]),
    event(["UID:c@google.com", ...base, "STATUS:CANCELLED", "X-GOOGLE-CONFERENCE:https://meet.google.com/ccc-dddd-eee"]),
    event(["UID:d@google.com", ...base, "X-GOOGLE-CONFERENCE:https://meet.google.com/ddd-eeee-fff", `ATTENDEE;PARTSTAT=DECLINED:mailto:${AGENT.toUpperCase()}`]),
    event(["UID:e@google.com", ...base, "X-GOOGLE-CONFERENCE:https://meet.google.com/eee-ffff-ggg", "ATTENDEE;PARTSTAT=DECLINED:mailto:bob@example.com"]),
  );
  assert.deepEqual(find(ics).map((o) => o.code).sort(), ["aaa-bbbb-ccc", "eee-ffff-ggg"]);
});

test("a weekly meeting gives one occurrence a week, at the right instant in Paris time", () => {
  const all = find(calendar(event(weekly)));
  assert.deepEqual(all.map((o) => o.start.toISOString()), [
    "2026-11-02T09:00:00.000Z",
    "2026-11-09T09:00:00.000Z",
    "2026-11-16T09:00:00.000Z",
  ]);
  assert.equal(new Set(all.map((o) => o.key)).size, 3);
});

test("a moved occurrence keeps its key at its new time; an excluded one is gone", () => {
  const moved = event([
    "UID:weekly@google.com",
    "RECURRENCE-ID;TZID=Europe/Paris:20261109T100000",
    "DTSTART;TZID=Europe/Paris:20261109T120000",
    "DTEND;TZID=Europe/Paris:20261109T130000",
    "SUMMARY:Weekly (moved)",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
  ]);
  const plain = find(calendar(event(weekly)));
  const all = find(calendar(event([...weekly, "EXDATE;TZID=Europe/Paris:20261116T100000"]), moved));
  assert.deepEqual(all.map((o) => o.start.toISOString()), ["2026-11-02T09:00:00.000Z", "2026-11-09T11:00:00.000Z"]);
  assert.equal(all[1].key, plain[1].key);
  assert.equal(all[1].summary, "Weekly (moved)");
});

test("the due meeting: from joinEarly before its start until its end, not handled, earliest first", () => {
  const at = (s, e, key) => ({ key, code: key, start: new Date(s), end: new Date(e) });
  const list = [at("2026-11-05T09:00:00Z", "2026-11-05T10:00:00Z", "a"), at("2026-11-05T09:30:00Z", "2026-11-05T10:30:00Z", "b")];
  const options = { joinEarlyMs: 60_000, handled: () => false };
  assert.equal(dueMeeting(list, new Date("2026-11-05T08:58:00Z"), options), null);
  assert.equal(dueMeeting(list, new Date("2026-11-05T08:59:30Z"), options).key, "a");
  assert.equal(dueMeeting(list, new Date("2026-11-05T09:45:00Z"), options).key, "a");
  assert.equal(dueMeeting(list, new Date("2026-11-05T09:45:00Z"), { ...options, handled: (o) => o.key === "a" }).key, "b");
  assert.equal(dueMeeting(list, new Date("2026-11-05T10:30:00Z"), options), null);
});

test("an invitation crafted to expand forever is skipped quickly; long daily series still work", () => {
  const started = Date.now();
  const all = find(calendar(
    event([
      "UID:flood@evil.example",
      "DTSTART:19700101T000000Z",
      "DTEND:19700101T000001Z",
      "RRULE:FREQ=SECONDLY",
      "X-GOOGLE-CONFERENCE:https://meet.google.com/zzz-zzzz-zzz",
    ]),
    event([
      "UID:daily@google.com",
      "DTSTART:20000103T090000Z",
      "DTEND:20000103T091500Z",
      "RRULE:FREQ=DAILY",
      "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
    ]),
  ));
  assert.ok(Date.now() - started < 3000, `took ${Date.now() - started} ms`);
  assert.ok(all.every((o) => o.code === "abc-defg-hij"));
  assert.equal(all.length, 29); // every day of the window
});

test("an invitation to one occurrence of someone else's series is joined", () => {
  const [one] = find(calendar(event([
    "UID:their-series@google.com",
    "RECURRENCE-ID:20261112T090000Z",
    "DTSTART:20261112T090000Z",
    "DTEND:20261112T100000Z",
    "SUMMARY:One of their weeklies",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
  ])));
  assert.equal(one.code, "abc-defg-hij");
  assert.equal(one.key, "their-series@google.com@2026-11-12T09:00:00.000Z");
});

test("only the organizers allowed bring the agent into a meeting", () => {
  const base = ["DTSTART:20261105T090000Z", "DTEND:20261105T093000Z", "SUMMARY:x"];
  const ics = calendar(
    event(["UID:a@google.com", ...base, "ORGANIZER;CN=Alice:mailto:Alice@Team.example", "X-GOOGLE-CONFERENCE:https://meet.google.com/aaa-bbbb-ccc"]),
    event(["UID:b@google.com", ...base, "ORGANIZER:mailto:bob@friend.example", "X-GOOGLE-CONFERENCE:https://meet.google.com/bbb-cccc-ddd"]),
    event(["UID:c@google.com", ...base, "ORGANIZER:mailto:eve@evil.example", "DESCRIPTION:https://meet.google.com/ccc-dddd-eee"]),
    event(["UID:d@google.com", ...base, "X-GOOGLE-CONFERENCE:https://meet.google.com/ddd-eeee-fff"]), // no organizer
  );
  const organizers = ["@team.example", "bob@friend.example"];
  const found = occurrences(ics, ...window, { agentEmail: AGENT, organizers });
  assert.deepEqual(found.map((o) => o.code).sort(), ["aaa-bbbb-ccc", "bbb-cccc-ddd"]);
});

test("an occurrence moved earlier, from beyond the window, into it is found", () => {
  const daily = [
    "UID:daily@google.com",
    "DTSTART:20261101T090000Z",
    "DTEND:20261101T091500Z",
    "RRULE:FREQ=DAILY",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
  ];
  const moved = event([
    "UID:daily@google.com",
    "RECURRENCE-ID:20261105T090000Z", // Thursday's, moved to Monday afternoon
    "DTSTART:20261102T140000Z",
    "DTEND:20261102T141500Z",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
  ]);
  const found = occurrences(calendar(event(daily), moved), new Date("2026-11-02T13:00:00Z"), new Date("2026-11-03T13:00:00Z"), { agentEmail: AGENT });
  assert.deepEqual(found.map((o) => o.start.toISOString()), ["2026-11-02T14:00:00.000Z", "2026-11-03T09:00:00.000Z"]);
  assert.equal(found[0].key, "daily@google.com@2026-11-05T09:00:00.000Z");
});

test("a rule with one BYHOUR and one BYMINUTE is a meeting, not a sub-daily rule", () => {
  const found = find(calendar(event([
    "UID:monday@other.example",
    "DTSTART:20261102T093000Z",
    "DTEND:20261102T100000Z",
    "RRULE:FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30;COUNT=2",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
  ])));
  assert.deepEqual(found.map((o) => o.start.toISOString()), ["2026-11-02T09:30:00.000Z", "2026-11-09T09:30:00.000Z"]);
});

test("a moved occurrence sent under an allowed series' UID by someone else is not joined", () => {
  const series = [
    "UID:weekly@google.com",
    "DTSTART:20261102T090000Z",
    "DTEND:20261102T100000Z",
    "RRULE:FREQ=WEEKLY;COUNT=3",
    "ORGANIZER:mailto:alice@team.example",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
  ];
  const forged = event([
    "UID:weekly@google.com",
    "RECURRENCE-ID:20261109T090000Z",
    "DTSTART:20261109T090000Z",
    "DTEND:20261109T100000Z",
    "ORGANIZER:mailto:eve@evil.example",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/eve-evil-eve",
  ]);
  const found = occurrences(calendar(event(series), forged), ...window, { agentEmail: AGENT, organizers: ["@team.example"] });
  // the forged one neither is joined nor hides the real occurrence it claims to move
  assert.deepEqual(found.map((o) => [o.code, o.start.toISOString()]), [
    ["abc-defg-hij", "2026-11-02T09:00:00.000Z"],
    ["abc-defg-hij", "2026-11-09T09:00:00.000Z"],
    ["abc-defg-hij", "2026-11-16T09:00:00.000Z"],
  ]);
  // nor does an event from someone else sent under the series' UID replace it
  const replaced = event(["UID:weekly@google.com", "DTSTART:20261103T090000Z", "DTEND:20261103T100000Z", "ORGANIZER:mailto:eve@evil.example", "X-GOOGLE-CONFERENCE:https://meet.google.com/eve-evil-eve"]);
  const both = occurrences(calendar(replaced, event(series)), ...window, { agentEmail: AGENT, organizers: ["@team.example"] });
  assert.equal(both.length, 3);
  assert.ok(both.every((o) => o.code === "abc-defg-hij"));
});

test("an organizer that is not a plain address is refused", () => {
  const base = ["DTSTART:20261105T090000Z", "DTEND:20261105T093000Z", "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij"];
  for (const organizer of ["eve@evil.example?@team.example", "eve@evil.example/@team.example", "@team.example", "eve@@team.example"]) {
    const ics = calendar(event(["UID:x@google.com", ...base, `ORGANIZER:mailto:${organizer}`]));
    assert.deepEqual(occurrences(ics, ...window, { agentEmail: AGENT, organizers: ["@team.example"] }), [], organizer);
  }
});

test("a moved occurrence of one series does not replace another series' occurrence at the same time", () => {
  const series = (uid, code) => event([
    `UID:${uid}`,
    "DTSTART:20261102T090000Z",
    "DTEND:20261102T100000Z",
    "RRULE:FREQ=WEEKLY;COUNT=2",
    `X-GOOGLE-CONFERENCE:https://meet.google.com/${code}`,
  ]);
  const moved = event([
    "UID:a@google.com",
    "RECURRENCE-ID:20261109T090000Z",
    "DTSTART:20261109T150000Z",
    "DTEND:20261109T160000Z",
    "X-GOOGLE-CONFERENCE:https://meet.google.com/aaa-aaaa-aaa",
  ]);
  const found = find(calendar(series("a@google.com", "aaa-aaaa-aaa"), series("b@google.com", "bbb-bbbb-bbb"), moved));
  const b = found.filter((o) => o.code === "bbb-bbbb-bbb").map((o) => o.start.toISOString());
  assert.deepEqual(b, ["2026-11-02T09:00:00.000Z", "2026-11-09T09:00:00.000Z"]);
  const a = found.filter((o) => o.code === "aaa-aaaa-aaa").map((o) => o.start.toISOString());
  assert.deepEqual(a, ["2026-11-02T09:00:00.000Z", "2026-11-09T15:00:00.000Z"]);
});
