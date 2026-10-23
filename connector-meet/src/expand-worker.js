// Runs occurrences() off the main thread, so that expand.js can stop it.
import { parentPort, workerData } from "node:worker_threads";

import { occurrences } from "./calendar.js";

const { icsText, from, to, agentEmail, organizers, skip } = workerData;
const found = occurrences(icsText, new Date(from), new Date(to), {
  agentEmail,
  organizers,
  skip: new Set(skip),
  onEvent: (uid) => parentPort.postMessage({ type: "event", uid }),
});
parentPort.postMessage({ type: "done", found: found.map((o) => ({ ...o, start: o.start.toISOString(), end: o.end.toISOString() })) });
