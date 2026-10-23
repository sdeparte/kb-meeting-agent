// Which invited meeting is due, from the calendar read every minute. The secret iCal address
// is a credential: it never appears in a log line, even inside an error message.
import { dueMeeting } from "./calendar.js";
import { readOccurrences } from "./expand.js";

const LOOK_AHEAD_MS = 24 * 3600_000;
const redact = (text) => String(text).replace(/https?:\/\/\S+/g, "<calendar address>");

export class Schedule {
  constructor({ fetchCalendar, agentEmail, organizers, handled, joinEarlyMs, log, clock = Date.now }) {
    Object.assign(this, { fetchCalendar, agentEmail, organizers, handled, joinEarlyMs, log, clock });
    this.failing = false;
    this.blocked = new Set(); // events whose expansion ran past its time limit
  }

  async next() {
    const now = new Date(this.clock());
    let found;
    try {
      const icsText = await this.fetchCalendar();
      const from = new Date(now.getTime() - LOOK_AHEAD_MS);
      found = await readOccurrences(icsText, from, new Date(now.getTime() + LOOK_AHEAD_MS), {
        agentEmail: this.agentEmail,
        organizers: this.organizers,
        blocked: this.blocked,
      });
    } catch (error) {
      if (!this.failing) this.log(`could not read the calendar: ${redact(error.cause?.message ?? error.message)}`);
      this.failing = true;
      return null;
    }
    this.failing = false;
    // Handled: that occurrence, or its call left on purpose since the occurrence could be joined
    const handled = (o) => this.handled.has(o.key) || (this.handled.leftAt(o.code) ?? -Infinity) >= o.start.getTime() - this.joinEarlyMs;
    return dueMeeting(found, now, { joinEarlyMs: this.joinEarlyMs, handled });
  }
}
