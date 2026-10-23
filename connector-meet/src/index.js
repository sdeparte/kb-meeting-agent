// kb-meeting-agent Google Meet connector: the agent's own Google account, in a browser, joins
// the meetings it is invited to (read from its calendar) and relays audio and chat. No meeting
// logic: every "!" line reaches the core, which writes every message (Meet has no buttons).
import { join } from "node:path";

import { captureAudio, openBrowser } from "kbma-browser/browser";
import { CommandLines } from "kbma-browser/commands";
import { SpeakerTracker } from "kbma-browser/speakers";

import { Outbound } from "./chat.js";
import { Handled } from "./handled.js";
import { Meeting } from "./meeting.js";
import { CONFIG_ERROR_EXIT, PROTOCOL_VERSION, encodeAudioFrame, message, parseMessage } from "./protocol.js";
import { Schedule } from "./schedule.js";
import * as ui from "./ui.js";

const {
  KBMA_CORE_URL,
  KBMA_SECRET,
  MEET_CALENDAR_ICS_URL,
  MEET_AGENT_EMAIL,
  MEET_BROWSER_PROFILE,
  MEET_ALLOWED_ORGANIZERS = "",
  MEET_HEADLESS = "true",
  MEET_JOIN_EARLY_SECONDS = "60",
  MEET_ADMISSION_TIMEOUT_SECONDS = "600",
} = process.env;
const log = (...args) => console.error(new Date().toISOString(), ...args);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const required = ["MEET_CALENDAR_ICS_URL", "MEET_AGENT_EMAIL", "MEET_BROWSER_PROFILE", "MEET_ALLOWED_ORGANIZERS"];
const missing = required.filter((name) => !process.env[name]?.trim());
if (missing.length) {
  log(`${missing.join(", ")} missing from connector.env`);
  process.exit(CONFIG_ERROR_EXIT);
}
// Who may bring the agent into a meeting: addresses, or whole domains written `@example.com`
const organizers = MEET_ALLOWED_ORGANIZERS.split(",").map((entry) => entry.trim().toLowerCase()).filter(Boolean);

let core = null;
const stats = { frames: 0, unknown_frames: 0 };
function send(type, fields = {}) {
  if (core?.readyState === WebSocket.OPEN) core.send(message(type, fields));
}
function sendAudio(userId, timestampMs, pcm) {
  stats.frames += 1;
  if (userId === "unknown") stats.unknown_frames += 1;
  if (core?.readyState === WebSocket.OPEN) core.send(encodeAudioFrame(userId, timestampMs, pcm));
}

const { context, page } = await openBrowser({ profileDir: MEET_BROWSER_PROFILE, headless: MEET_HEADLESS !== "false" });
for (const event of ["crash", "close"]) {
  page.on(event, () => {
    log(`the Meet page ${event === "crash" ? "crashed" : "closed"}; exiting so the core restarts the connector`);
    process.exit(1);
  });
}
const handled = new Handled({ file: join(MEET_BROWSER_PROFILE, "kbma-handled.json") });
const commands = new CommandLines();
const meeting = new Meeting({
  ui,
  page,
  makeTracker: (selfId) => new SpeakerTracker({ selfId }), // one per meeting
  handled,
  commands,
  sendToCore: send,
  sendAudio,
  log,
  admissionTimeoutMs: Number(MEET_ADMISSION_TIMEOUT_SECONDS) * 1000,
});
const outbound = new Outbound({ ui, page, currentCode: () => meeting.current?.code ?? null, sendToCore: send, log });
await captureAudio(page, (samples, t) => meeting.onSamples(samples, t), log);

async function exitIfLoggedOut() {
  if (await ui.isLoggedIn(page)) return;
  log('the Meet browser profile is not logged in: run "npm run login" in connector-meet');
  await sleep(60_000); // the core restarts the connector: not faster than once a minute
  process.exit(1);
}
await exitIfLoggedOut();

function onCoreMessage(event) {
  let msg;
  try {
    msg = parseMessage(event.data);
  } catch (error) {
    log("invalid message from the core", error.message);
    return;
  }
  if (msg.type === "commands") commands.setCatalog(msg.commands ?? []);
  // `leave` waits for the messages before it: the last answers reach the chat first.
  const done =
    msg.type === "leave" ? outbound.enqueue(msg).then(() => meeting.onCore(msg)) : Promise.all([outbound.enqueue(msg), meeting.onCore(msg)]);
  done.catch((error) => {
    log(`handling ${msg.type} failed`, error);
    send("error", { message: `${msg.type}: ${error.message}` });
  });
}

core = new WebSocket(KBMA_CORE_URL);
core.addEventListener("open", () =>
  send("hello", { secret: KBMA_SECRET, protocol: PROTOCOL_VERSION, connector: "meet/0.1.0", capabilities: { buttons: false } }),
);
core.addEventListener("message", onCoreMessage);
core.addEventListener("close", async () => {
  log("core connection closed; exiting so the core restarts the connector");
  await context.close().catch(() => {});
  process.exit(1);
});

const schedule = new Schedule({
  fetchCalendar: async () => {
    const response = await fetch(MEET_CALENDAR_ICS_URL);
    if (!response.ok) throw new Error(`the calendar answered ${response.status}`);
    return response.text();
  },
  agentEmail: MEET_AGENT_EMAIL,
  organizers,
  handled,
  joinEarlyMs: Number(MEET_JOIN_EARLY_SECONDS) * 1000,
  log,
});

let busy = false; // joining, or checking the login: the page is in use
async function tick() {
  if (busy || meeting.current) return;
  busy = true;
  try {
    if (meeting.wanted) {
      // The core's meeting goes on (after a restart, or a drop): back to it, nothing else.
      log(`rejoining the running meeting (${meeting.wanted})`);
      await meeting.rejoin();
      return;
    }
    const due = await schedule.next();
    if (due) {
      log(`joining ${due.summary} (${due.code})`);
      await meeting.join(due);
    }
  } catch (error) {
    log("joining a meeting failed", error.message);
  } finally {
    busy = false;
  }
}

let polling = false;
setInterval(async () => {
  if (polling || busy) return;
  polling = true;
  try {
    await meeting.poll(Date.now());
  } catch (error) {
    log("reading the meeting failed", error.message);
  } finally {
    polling = false;
  }
}, 100).unref();

setInterval(tick, 60_000).unref();
setInterval(() => meeting.wanted && !meeting.current && tick(), 5_000).unref(); // back quickly after a drop
setInterval(() => send("stats", { ...stats }), 60_000).unref();
setInterval(async () => {
  if (busy || meeting.current) return;
  busy = true;
  try {
    await exitIfLoggedOut();
  } finally {
    busy = false;
  }
}, 5 * 60_000).unref();

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    await context.close().catch(() => {});
    process.exit(0);
  });
}

log("ready: watching the calendar for invited meetings");
await tick(); // a meeting still in progress after a crash is joined again, and resumed by the core
