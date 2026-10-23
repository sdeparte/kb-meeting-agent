// kb-meeting-agent Slack connector: a Bolt app for messages, buttons, forms and commands, and the
// agent's own Slack account in a browser for the huddle's audio. No meeting logic: every
// command reaches the core as the "!" line it stands for.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import bolt from "@slack/bolt";
import { captureAudio, openBrowser } from "kbma-browser/browser";
import { CommandLines } from "kbma-browser/commands";
import { SpeakerTracker } from "kbma-browser/speakers";

import { Huddle } from "./huddle.js";
import { Members, chatFromMessage, modalView, slashToChat } from "./inbound.js";
import { Outbound } from "./outbound.js";
import { PROTOCOL_VERSION, encodeAudioFrame, message, parseMessage } from "./protocol.js";
import * as ui from "./ui.js";

const {
  KBMA_CORE_URL,
  KBMA_SECRET,
  SLACK_BOT_TOKEN,
  SLACK_APP_TOKEN,
  SLACK_AGENT_USER_ID,
  SLACK_WORKSPACE_URL,
  SLACK_BROWSER_PROFILE,
  SLACK_HEADLESS = "true",
} = process.env;
const log = (...args) => console.error(new Date().toISOString(), ...args);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

const app = new bolt.App({ token: SLACK_BOT_TOKEN, appToken: SLACK_APP_TOKEN, socketMode: true, logLevel: bolt.LogLevel.WARN });
const members = new Members();
// The meeting's thread, next to the browser profile: a restarted connector answers in it.
const threadFile = join(SLACK_BROWSER_PROFILE, "kbma-thread.json");
const threadStore = {
  load: () => {
    try {
      return JSON.parse(readFileSync(threadFile, "utf8"));
    } catch {
      return null;
    }
  },
  save: (state) => {
    try {
      mkdirSync(SLACK_BROWSER_PROFILE, { recursive: true });
      writeFileSync(threadFile, JSON.stringify(state));
    } catch (error) {
      log("keeping the meeting's thread failed", error.message);
    }
  },
};
const outbound = new Outbound({ client: app.client, log, sendToCore: send, store: threadStore });
const huddleChannels = new Map(); // huddle call id -> its channel, from the huddle's thread message
const names = new Map(); // user id -> display name

function nameOf(id) {
  if (!names.has(id)) {
    names.set(id, id);
    app.client.users
      .info({ user: id })
      .then(({ user }) => names.set(id, user.profile?.display_name || user.real_name || id))
      .catch(() => {});
  }
  return names.get(id);
}

// A person's chat line: it names the huddle as its voice channel only when typed in the
// huddle's channel, so that /meeting start elsewhere cannot open a meeting nobody hears.
function toChat(text, userId, channel) {
  send("chat", { text, user: { id: userId, name: nameOf(userId) }, text_channel_id: channel, voice_channel_id: huddle.voiceFor(channel) });
}

// Once a decision is validated, edited or ignored, its Edit form is no longer needed.
function forgetModals(id) {
  const prefix = id.slice(0, id.lastIndexOf(":") + 1);
  for (const key of outbound.modals.keys()) if (key.startsWith(prefix)) outbound.modals.delete(key);
}

for (const command of ["/meeting", "/ask"]) {
  app.command(command, async ({ command: cmd, ack }) => {
    await ack();
    toChat(slashToChat(command, cmd.text), cmd.user_id, cmd.channel_id);
  });
}

app.message(async ({ message: event }) => {
  if (event.subtype === "huddle_thread" && event.room?.id) huddleChannels.set(event.room.id, event.channel);
  const line = chatFromMessage(event, { meetingChannel: outbound.left ? null : outbound.channel, agentUserId: SLACK_AGENT_USER_ID });
  if (line) toChat(line.text, line.userId, event.channel);
});

app.action(/.*/, async ({ action, body, ack, client }) => {
  await ack();
  const modal = outbound.modals.get(action.action_id);
  if (modal) {
    await client.views.open({ trigger_id: body.trigger_id, view: modalView(action.action_id, modal) });
    return;
  }
  forgetModals(action.action_id);
  send("button", { custom_id: action.action_id, user: { id: body.user.id, name: nameOf(body.user.id) } });
});

app.view(/.*/, async ({ ack, view, body }) => {
  await ack();
  forgetModals(view.callback_id);
  send("modal_submit", {
    custom_id: view.callback_id,
    value: view.state.values.value.value.value,
    user: { id: body.user.id, name: nameOf(body.user.id) },
  });
});

// Who is in which call, for the channel of the huddle the account joins. The members of the
// meeting come from the huddle window (Huddle), which also knows those who joined before the
// connector started.
app.event("user_huddle_changed", async ({ event }) => members.update(event));

const { context, page } = await openBrowser({ profileDir: SLACK_BROWSER_PROFILE, headless: SLACK_HEADLESS !== "false" });
page.on("crash", () => {
  log("the Slack page crashed; exiting so the core restarts the connector");
  process.exit(1);
});
page.on("close", () => {
  log("the Slack page closed; exiting so the core restarts the connector");
  process.exit(1);
});
const commands = new CommandLines();
const huddle = new Huddle({
  ui,
  page,
  makeTracker: () => new SpeakerTracker({ selfId: SLACK_AGENT_USER_ID }), // one per huddle
  agentUserId: SLACK_AGENT_USER_ID,
  nameOf,
  commands,
  sendToCore: send,
  sendAudio,
  log,
  // The channel of the huddle the account just joined: its call id (from the account's own
  // user_huddle_changed) mapped to the channel by the huddle's thread message. A huddle that
  // started before the connector did is looked up in the running meeting's channel only:
  // a huddle whose channel stays unknown is never taken for the meeting's.
  channelOf: async (meetingChannel) => {
    let checked = null;
    for (let attempt = 0; attempt < 40; attempt++) {
      const call = members.callOf(SLACK_AGENT_USER_ID);
      const channel = huddleChannels.get(call);
      if (channel) return channel;
      if (call && meetingChannel && checked !== call) {
        checked = call;
        if (await hasHuddleThread(meetingChannel, call)) return meetingChannel;
      }
      await sleep(250);
    }
    return null;
  },
});

// Whether the huddle `call` was started in `channel`: its thread message is in the channel's
// recent history.
async function hasHuddleThread(channel, call) {
  try {
    const { messages = [] } = await app.client.conversations.history({ channel, limit: 200 });
    return messages.some((m) => m.subtype === "huddle_thread" && m.room?.id === call);
  } catch (error) {
    log("reading the meeting's channel failed", error.data?.error ?? error.message);
    return false;
  }
}
await captureAudio(page, (samples, t) => huddle.onSamples(samples, t), log);
await page.goto(SLACK_WORKSPACE_URL);
if (!(await ui.isLoggedIn(page))) {
  log('the Slack browser profile is not logged in: run "npm run login" in connector-slack');
  await sleep(60_000); // the core restarts the connector: not faster than once a minute
  process.exit(1);
}
await app.start();

function onCoreMessage(event) {
  let msg;
  try {
    msg = parseMessage(event.data);
  } catch (error) {
    log("invalid message from the core", error.message);
    return;
  }
  if (msg.type === "commands") commands.setCatalog(msg.commands ?? []);
  Promise.all([outbound.enqueue(msg), huddle.onCore(msg)]).catch((error) => {
    log(`handling ${msg.type} failed`, error);
    send("error", { message: `${msg.type}: ${error.message}` });
  });
}

core = new WebSocket(KBMA_CORE_URL);
core.addEventListener("open", () =>
  send("hello", { secret: KBMA_SECRET, protocol: PROTOCOL_VERSION, connector: "slack/0.1.0", capabilities: { buttons: true } }),
);
core.addEventListener("message", onCoreMessage);
core.addEventListener("close", async () => {
  log("core connection closed; exiting so the core restarts the connector");
  await context.close().catch(() => {});
  process.exit(1);
});
log("ready: waiting for huddle invitations");

let polling = false;
setInterval(async () => {
  if (polling) return;
  polling = true;
  try {
    await huddle.poll(Date.now());
  } catch (error) {
    log("reading the huddle failed", error.message);
  } finally {
    polling = false;
  }
}, 100).unref();

setInterval(() => send("stats", { ...stats }), 60_000).unref();

// A session that expires while the connector runs: say so and let the core restart it.
setInterval(async () => {
  if (huddle.channel || (await ui.isLoggedIn(page))) return;
  log('the Slack browser profile is no longer logged in: run "npm run login" in connector-slack');
  await sleep(60_000);
  process.exit(1);
}, 5 * 60_000).unref();

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    await context.close().catch(() => {});
    process.exit(0);
  });
}

for (;;) {
  try {
    await huddle.acceptInvite();
  } catch (error) {
    log("handling a huddle invitation failed", error.message);
  }
  await sleep(2_000); // an ignored invitation stays on screen a while: do not spin on it
}
