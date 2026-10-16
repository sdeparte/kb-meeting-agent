// kb-meeting-agent Discord connector: translates Discord <-> protocol v1. No business logic.
import opus from "@discordjs/opus";
import { EndBehaviorType, VoiceConnectionStatus, entersState, joinVoiceChannel } from "@discordjs/voice";
import {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  Client,
  Events,
  GatewayIntentBits,
  MessageFlags,
  ModalBuilder,
  TextInputBuilder,
  TextInputStyle,
} from "discord.js";

import { COMMANDS, commandName, commandOptions } from "./commands.js";
import { downsample48kStereoTo16kMono } from "./downsample.js";
import { PROTOCOL_VERSION, encodeAudioFrame, message, parseMessage } from "./protocol.js";
import { isLoggableVoiceDebug, truncate } from "./text.js";
import { UtteranceTracker } from "./utterances.js";

const { KBMA_CORE_URL, KBMA_SECRET, DISCORD_TOKEN, DISCORD_GUILD_ID } = process.env;
const log = (...args) => console.error(new Date().toISOString(), ...args);

const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates] });
let core = null; // opened once logged in to Discord, so a join is never handled too early
const interactions = new Map(); // interaction id -> deferred interaction awaiting a reply
const modals = new Map(); // button custom id -> modal descriptor
const optedOut = new Set();
const stats = { decrypt_errors: 0, users: new Map() };
let voice = null; // { connection, channel, textChannelId, tracker, subscribed }
let wanted = null; // { voiceChannelId, textChannelId } while the core wants us in a channel
let rejoinTimer = null;

function send(type, fields = {}) {
  if (core?.readyState === WebSocket.OPEN) core.send(message(type, fields));
}

function userStats(userId) {
  if (!stats.users.has(userId)) stats.users.set(userId, { packets: 0, opus_errors: 0, stream_errors: 0, utterances: 0 });
  return stats.users.get(userId);
}

function speakerName(userId) {
  return voice?.channel.members.get(userId)?.displayName ?? userId;
}

function emit(events, userId) {
  for (const event of events) {
    if (event.type === "utterance_start") userStats(userId).utterances += 1;
    send(event.type, { user_id: event.userId ?? userId, speaker_name: speakerName(event.userId ?? userId), t: event.t });
  }
}

function reportMembers() {
  if (!voice) return;
  const members = [...voice.channel.members.values()].map((m) => ({ id: m.id, name: m.displayName, bot: m.user.bot }));
  send("members", { members });
}

function subscribe(userId) {
  const current = voice;
  if (!current || optedOut.has(userId)) return;
  emit(current.tracker.start(userId, Date.now()), userId);
  if (current.subscribed.has(userId)) return;
  current.subscribed.add(userId);
  const decoder = new opus.OpusEncoder(48000, 2);
  const counters = userStats(userId);
  const stream = current.connection.receiver.subscribe(userId, { end: { behavior: EndBehaviorType.Manual } });
  stream.on("data", (packet) => {
    if (optedOut.has(userId) || voice !== current) return;
    counters.packets += 1;
    let pcm;
    try {
      pcm = decoder.decode(packet);
    } catch {
      counters.opus_errors += 1;
      return;
    }
    const now = Date.now();
    emit(current.tracker.packet(userId, now), userId);
    if (core?.readyState === WebSocket.OPEN) core.send(encodeAudioFrame(userId, now, downsample48kStereoTo16kMono(pcm)));
  });
  stream.on("error", (error) => {
    counters.stream_errors += 1;
    log(`receive stream error for ${userId}: ${error.message}`);
    current.subscribed.delete(userId);
  });
  stream.on("close", () => current.subscribed.delete(userId));
}

function leaveVoice() {
  if (!voice) return;
  const current = voice;
  voice = null;
  emit(current.tracker.endAll(Date.now()), null);
  current.connection.destroy();
}

// Retry while the core wants us in the channel: 2 s, 4 s, 8 s... up to 60 s.
function scheduleRejoin(attempt) {
  clearTimeout(rejoinTimer);
  if (!wanted) return;
  const delay = Math.min(2_000 * 2 ** attempt, 60_000);
  const { voiceChannelId, textChannelId } = wanted;
  rejoinTimer = setTimeout(() => {
    joinVoice(voiceChannelId, textChannelId, attempt).catch((error) => {
      log("rejoin failed", error);
      scheduleRejoin(attempt + 1);
    });
  }, delay);
}

async function joinVoice(voiceChannelId, textChannelId, attempt = 0) {
  clearTimeout(rejoinTimer);
  wanted = { voiceChannelId, textChannelId };
  const status = voice?.connection.state.status;
  if (voice?.channel.id === voiceChannelId && status !== VoiceConnectionStatus.Destroyed && status !== VoiceConnectionStatus.Disconnected) {
    // Already there (or on the way): a repeated join must not tear down a working connection.
    voice.textChannelId = textChannelId;
    send("voice_state", { status });
    if (status === VoiceConnectionStatus.Ready) reportMembers();
    return;
  }
  leaveVoice();
  const channel = await client.channels.fetch(voiceChannelId);
  const connection = joinVoiceChannel({
    channelId: channel.id,
    guildId: channel.guild.id,
    adapterCreator: channel.guild.voiceAdapterCreator,
    selfDeaf: false,
    selfMute: true,
    debug: true,
  });
  const current = { connection, channel, textChannelId, tracker: new UtteranceTracker(), subscribed: new Set() };
  voice = current;
  connection.on("debug", (line) => {
    if (/failed to decrypt/i.test(line)) {
      stats.decrypt_errors += 1; // counted in the stats, not logged one by one
      return;
    }
    if (isLoggableVoiceDebug(line)) log("[voice]", line);
  });
  connection.on("error", (error) => {
    log("voice error", error);
    send("error", { message: `voice: ${error.message}` });
  });
  connection.on("stateChange", (_from, to) => {
    // A replaced connection reports "destroyed": that is not a loss of the current one.
    if (voice === current) send("voice_state", { status: to.status });
  });
  connection.on(VoiceConnectionStatus.Disconnected, async () => {
    if (voice !== current) return;
    try {
      await Promise.race([
        entersState(connection, VoiceConnectionStatus.Signalling, 5_000),
        entersState(connection, VoiceConnectionStatus.Connecting, 5_000),
      ]);
    } catch {
      if (voice !== current) return;
      send("voice_state", { status: "lost" });
      leaveVoice();
      scheduleRejoin(0);
    }
  });
  try {
    await entersState(connection, VoiceConnectionStatus.Ready, 30_000);
  } catch {
    if (voice !== current) return; // replaced by a newer attempt meanwhile: nothing to do
    send("error", { message: "voice connection timed out: check the bot's Connect permission on the channel" });
    leaveVoice();
    scheduleRejoin(attempt + 1);
    return;
  }
  connection.receiver.speaking.on("start", (userId) => subscribe(userId));
  reportMembers();
}

function components(buttons = []) {
  if (!buttons.length) return [];
  const row = new ActionRowBuilder();
  for (const button of buttons.slice(0, 5)) {
    const style = button.id.endsWith(":validate") ? ButtonStyle.Success : ButtonStyle.Secondary;
    row.addComponents(new ButtonBuilder().setCustomId(button.id).setLabel(button.label.slice(0, 80)).setStyle(style));
    if (button.modal) modals.set(button.id, button.modal);
  }
  return [row];
}

async function handleCore(msg) {
  if (msg.type === "join") {
    await joinVoice(msg.voice_channel_id, msg.text_channel_id);
  } else if (msg.type === "leave") {
    wanted = null;
    clearTimeout(rejoinTimer);
    leaveVoice();
  } else if (msg.type === "send") {
    const channel = await client.channels.fetch(msg.channel_id ?? voice?.textChannelId);
    const sent = await channel.send({
      content: truncate(msg.text),
      components: components(msg.buttons),
      allowedMentions: { parse: [] }, // never ping anyone from a transcript or a KB quote
    });
    send("sent", { request_id: msg.request_id, message_id: sent.id });
  } else if (msg.type === "reply") {
    const interaction = interactions.get(msg.interaction_id);
    interactions.delete(msg.interaction_id);
    if (interaction) await interaction.editReply({ content: truncate(msg.text) });
  } else if (msg.type === "optout") {
    optedOut.add(msg.user_id);
    if (voice) emit(voice.tracker.end(msg.user_id, Date.now()), msg.user_id);
  } else if (msg.type === "modals") {
    // After a restart: the Edit modals of messages posted by the previous process.
    for (const { id, modal } of msg.modals ?? []) modals.set(id, modal);
  }
}

// Once a decision is validated, edited or ignored, its Edit modal is no longer needed.
function forgetModals(customId) {
  const prefix = customId.slice(0, customId.lastIndexOf(":") + 1);
  for (const id of modals.keys()) if (id.startsWith(prefix)) modals.delete(id);
}

function userOf(interaction) {
  return { id: interaction.user.id, name: interaction.member?.displayName ?? interaction.user.username };
}

client.on(Events.InteractionCreate, async (interaction) => {
  try {
    if (interaction.isChatInputCommand()) {
      const name = commandName(interaction);
      await interaction.deferReply(name === "meeting_optout" ? { flags: MessageFlags.Ephemeral } : {});
      interactions.set(interaction.id, interaction);
      send("command", {
        interaction_id: interaction.id,
        name,
        options: commandOptions(interaction),
        user: userOf(interaction),
        text_channel_id: interaction.channelId,
        voice_channel_id: interaction.member?.voice?.channelId ?? null,
      });
    } else if (interaction.isButton()) {
      const modal = modals.get(interaction.customId);
      if (modal) {
        const input = new TextInputBuilder()
          .setCustomId("value")
          .setLabel(modal.label.slice(0, 45))
          .setStyle(TextInputStyle.Paragraph)
          .setValue(modal.value.slice(0, 4000))
          .setRequired(true);
        await interaction.showModal(
          new ModalBuilder()
            .setCustomId(interaction.customId)
            .setTitle(modal.title.slice(0, 45))
            .addComponents(new ActionRowBuilder().addComponents(input)),
        );
        return;
      }
      await interaction.deferUpdate();
      forgetModals(interaction.customId);
      send("button", { custom_id: interaction.customId, user: userOf(interaction) });
    } else if (interaction.isModalSubmit()) {
      if (interaction.isFromMessage()) await interaction.deferUpdate();
      else await interaction.deferReply({ flags: MessageFlags.Ephemeral });
      forgetModals(interaction.customId);
      send("modal_submit", {
        custom_id: interaction.customId,
        value: interaction.fields.getTextInputValue("value"),
        user: userOf(interaction),
      });
    }
  } catch (error) {
    log("interaction failed", error);
  }
});

client.on(Events.VoiceStateUpdate, (before, after) => {
  if (voice && (before.channelId === voice.channel.id || after.channelId === voice.channel.id)) reportMembers();
});

function connectCore() {
  core = new WebSocket(KBMA_CORE_URL);
  core.addEventListener("open", () => send("hello", { secret: KBMA_SECRET, protocol: PROTOCOL_VERSION, connector: "discord/0.1.0" }));
  core.addEventListener("message", onCoreMessage);
  core.addEventListener("close", () => {
    log("core connection closed; exiting so the core restarts the connector");
    leaveVoice();
    process.exit(1);
  });
}

client.once(Events.ClientReady, async () => {
  const guild = await client.guilds.fetch(DISCORD_GUILD_ID);
  await guild.commands.set(COMMANDS);
  log(`ready as ${client.user.tag}; commands registered on ${guild.name}`);
  connectCore();
});

function onCoreMessage(event) {
  let msg;
  try {
    msg = parseMessage(event.data);
  } catch (error) {
    log("invalid message from the core", error.message);
    return;
  }
  handleCore(msg).catch((error) => {
    log(`handling ${msg.type} failed`, error);
    send("error", { message: `${msg.type}: ${error.message}` });
  });
}

// Utterances end on silence measured from the last packet, not on Discord's "speaking end".
setInterval(() => {
  if (voice) emit(voice.tracker.endSilent(Date.now()), null);
}, 200).unref();

setInterval(() => {
  send("stats", { decrypt_errors: stats.decrypt_errors, users: [...stats.users].map(([id, s]) => ({ id, ...s })) });
}, 60_000).unref();

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    leaveVoice();
    client.destroy();
    process.exit(0);
  });
}

client.login(DISCORD_TOKEN).catch((error) => {
  // The core is not connected yet (that waits for Discord): the exit code and the log
  // tell the supervisor and the operator.
  log(`Discord login failed: ${error.message}`);
  process.exit(1);
});
