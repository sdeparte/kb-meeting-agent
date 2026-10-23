// The agent's calendar, read from Google Calendar's secret iCal address: the Meet meetings it
// is invited to, recurring ones expanded, moved occurrences at their new time, cancelled or
// declined ones left out.
import ICAL from "ical.js";

// Anyone can invite the agent, so an invitation must not make the expansion run forever: no
// rule repeating more than once a day (no meeting does), and a bounded number of steps. A rule
// can still spin inside ical.js without yielding (one that matches no date): expand.js runs
// this in a worker with a time limit.
const SUB_DAILY = new Set(["SECONDLY", "MINUTELY", "HOURLY"]);

function moreThanDaily(rule) {
  if (SUB_DAILY.has(String(rule?.freq).toUpperCase())) return true;
  const parts = rule?.parts ?? {};
  const times = (name) => parts[name]?.length || 1;
  return times("BYHOUR") * times("BYMINUTE") * times("BYSECOND") > 1;
}
const MAX_STEPS_PER_EVENT = 20_000; // a daily meeting for 50 years
const MAX_STEPS = 200_000;

const MEET_LINK = /https:\/\/meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})/;

function meetCode(component) {
  for (const name of ["x-google-conference", "location", "description"]) {
    const match = String(component.getFirstPropertyValue(name) ?? "").match(MEET_LINK);
    if (match) return match[1];
  }
  return null;
}

// Anyone can invite the agent: only the organizers allowed (`alice@example.com`, or a whole
// `@example.com`) bring it into a meeting, with the project's knowledge base. Checked on every
// component kept: a moved occurrence is a component of its own, which anyone can send under a
// series' UID. Anything but a plain address is refused.
const ADDRESS = /^[a-z0-9._%+-]+@([a-z0-9-]+\.)+[a-z]{2,}$/;

function organizedBy(component, organizers) {
  if (!organizers) return true;
  const address = String(component.getFirstPropertyValue("organizer") ?? "").replace(/^mailto:/i, "").toLowerCase();
  if (!ADDRESS.test(address)) return false;
  const domain = address.slice(address.indexOf("@"));
  return organizers.some((allowed) => allowed === address || allowed === domain);
}

function declinedBy(component, email) {
  if (!email) return false;
  return component.getAllProperties("attendee").some((attendee) => {
    const address = String(attendee.getFirstValue() ?? "").replace(/^mailto:/i, "");
    return address.toLowerCase() === email.toLowerCase() && String(attendee.getParameter("partstat")).toUpperCase() === "DECLINED";
  });
}

function occurrence(item, start, end, key, { agentEmail, organizers }) {
  const component = item.component;
  const code = meetCode(component);
  if (!code || String(component.getFirstPropertyValue("status") ?? "").toUpperCase() === "CANCELLED") return null;
  if (declinedBy(component, agentEmail) || !organizedBy(component, organizers)) return null;
  return { key, summary: item.summary ?? "", code, url: `https://meet.google.com/${code}`, start, end };
}

// `skip`: UIDs not to expand; `onEvent(uid)`: called before each recurring event is expanded;
// `organizers`: lowercase addresses or `@domains` allowed to invite the agent (null: everyone).
export function occurrences(icsText, from, to, { agentEmail, organizers = null, skip = new Set(), onEvent = () => {} }) {
  const root = new ICAL.Component(ICAL.parse(icsText));
  for (const zone of root.getAllSubcomponents("vtimezone")) ICAL.TimezoneService.register(zone);
  // A component from someone else, sent under a series' UID, must not replace that series or
  // one of its occurrences: only one from the same organizer is related to it.
  const sameOrganizer = (a, b) => String(a.getFirstPropertyValue("organizer") ?? "").toLowerCase() === String(b.getFirstPropertyValue("organizer") ?? "").toLowerCase();
  const masters = new Map();
  const exceptions = [];
  for (const component of root.getAllSubcomponents("vevent")) {
    if (component.hasProperty("recurrence-id")) exceptions.push(component);
    else if (organizedBy(component, organizers) && !masters.has(component.getFirstPropertyValue("uid"))) {
      // `exceptions: []`: ical.js would otherwise relate every moved occurrence of the calendar
      // to this series, whatever its UID
      masters.set(component.getFirstPropertyValue("uid"), new ICAL.Event(component, { exceptions: [] }));
    }
  }
  const orphans = []; // one occurrence of a series the agent is invited to alone
  for (const exception of exceptions) {
    const master = masters.get(exception.getFirstPropertyValue("uid"));
    if (!master) orphans.push(new ICAL.Event(exception));
    else if (sameOrganizer(master.component, exception)) master.relateException(exception);
  }

  const found = [];
  const keep = (item, startTime, endTime, key) => {
    const start = startTime.toJSDate();
    const end = endTime.toJSDate();
    if (end <= from || start >= to) return;
    const entry = occurrence(item, start, end, key, { agentEmail, organizers });
    if (entry) found.push(entry);
  };
  let steps = 0;
  for (const [uid, event] of masters) {
    if (skip.has(uid)) continue;
    if (!event.isRecurring()) {
      keep(event, event.startDate, event.endDate, `${uid}@${event.startDate.toJSDate().toISOString()}`);
      continue;
    }
    const rules = event.component.getAllProperties("rrule").map((p) => p.getFirstValue());
    if (rules.some(moreThanDaily)) continue;
    onEvent(uid);
    const iterator = event.iterator();
    let eventSteps = 0;
    const seen = new Set(); // the recurrence ids looked at
    for (let next = iterator.next(); next; next = iterator.next()) {
      if (++eventSteps > MAX_STEPS_PER_EVENT || ++steps > MAX_STEPS) break;
      const details = event.getOccurrenceDetails(next);
      // An occurrence moved later than `to` from a slot before it is still looked at.
      if (next.toJSDate() >= to && details.startDate.toJSDate() >= to) break;
      const recurrenceId = details.recurrenceId.toJSDate().toISOString();
      seen.add(recurrenceId);
      keep(details.item, details.startDate, details.endDate, `${uid}@${recurrenceId}`);
    }
    // And one moved earlier, into the window, from a slot the loop did not reach.
    for (const exception of Object.values(event.exceptions)) {
      const recurrenceId = exception.recurrenceId.toJSDate().toISOString();
      if (!seen.has(recurrenceId)) keep(exception, exception.startDate, exception.endDate, `${uid}@${recurrenceId}`);
    }
  }
  for (const event of orphans) {
    const uid = event.uid;
    if (skip.has(uid) || !organizedBy(event.component, organizers)) continue;
    keep(event, event.startDate, event.endDate, `${uid}@${event.recurrenceId.toJSDate().toISOString()}`);
  }
  return found.sort((a, b) => a.start - b.start);
}

export function dueMeeting(list, now, { joinEarlyMs, handled }) {
  return (
    list
      .filter((o) => o.start.getTime() - joinEarlyMs <= now.getTime() && now < o.end && !handled(o))
      .sort((a, b) => a.start - b.start)[0] ?? null
  );
}
