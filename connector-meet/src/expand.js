// Reads the calendar's occurrences in a worker, with a time limit per recurring event. The
// worker says which event it starts; one that runs past its own limit (a rule built to match
// nothing makes ical.js spin) is added to `blocked` and the read starts again without it. Each
// attempt blocks a different event, so any number of them cannot keep the agent from its
// meetings, and the time spent on one event never counts against another. A whole read also
// has a total budget: past it, it fails (logged, retried a minute later) and the events
// blocked so far stay blocked, so the next read gets further.
import { Worker } from "node:worker_threads";

function attempt(icsText, from, to, { agentEmail, organizers }, blocked, timeoutMs, deadline) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./expand-worker.js", import.meta.url), {
      workerData: { icsText, from: from.toISOString(), to: to.toISOString(), agentEmail, organizers, skip: [...blocked] },
    });
    let current = null;
    let timer = null;
    const arm = () => {
      clearTimeout(timer);
      const remaining = deadline - Date.now();
      // Before the first recurring event (parsing, the events that do not repeat), the time grows
      // with the calendar, not with one invitation: only the total budget applies.
      const overall = current === null || remaining <= timeoutMs;
      timer = setTimeout(() => {
        worker.terminate();
        resolve(overall ? { overBudget: true } : { timedOut: current });
      }, Math.max(0, overall ? remaining : timeoutMs));
    };
    arm();
    worker.on("message", (message) => {
      if (message.type === "event") {
        current = message.uid;
        arm();
        return;
      }
      clearTimeout(timer);
      worker.terminate();
      resolve({ found: message.found });
    });
    worker.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

export async function readOccurrences(
  icsText,
  from,
  to,
  { agentEmail, organizers = null, timeoutMs = 2_000, totalTimeoutMs = 30_000, blocked = new Set() },
) {
  const deadline = Date.now() + totalTimeoutMs;
  for (;;) {
    const result = await attempt(icsText, from, to, { agentEmail, organizers }, blocked, timeoutMs, deadline);
    if (result.overBudget) throw new Error("reading the calendar timed out (total budget)");
    if (result.found) return result.found.map((o) => ({ ...o, start: new Date(o.start), end: new Date(o.end) }));
    // Out of time on an event already skipped: nothing to block.
    if (blocked.has(result.timedOut)) throw new Error("reading the calendar timed out");
    blocked.add(result.timedOut);
  }
}
