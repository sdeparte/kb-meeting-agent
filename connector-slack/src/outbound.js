// The core's messages, carried out on Slack through the app (Bolt's Web API client). The agent
// opens its own thread: its first message after a join is posted in the huddle's channel, the
// next ones answer it.
const MAX_TEXT = 3000; // Slack's limit for a section block's text

// Slack turns <!channel>, <!here> and <@U…> into notifications: transcripts and KB quotes
// must never ping anyone, so its markup characters are escaped.
export function escapeMrkdwn(text) {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

// The core writes Markdown links, [label](url) (code sources, files of a decision): Slack's
// are <url|label>. Applied to escaped text, so that no other markup gets through.
export function slackLinks(text) {
  return text.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, label, url) => `<${url}|${label.replaceAll("|", "/")}>`);
}

// Text within Slack's limit, cut with "…" outside an entity (&amp;) or a link (<url|label>).
export function fitText(text, max = MAX_TEXT) {
  if (text.length <= max) return text;
  let cut = max - 1;
  const entity = text.lastIndexOf("&", cut);
  if (entity > cut - 6 && !text.slice(entity, cut).includes(";")) cut = entity;
  const link = text.lastIndexOf("<", cut);
  if (link > text.lastIndexOf(">", cut - 1)) cut = link;
  return `${text.slice(0, cut)}…`;
}

export class Outbound {
  // `store`: where the meeting's thread is kept ({ load, save }), so that a restarted connector
  // goes on answering in it.
  constructor({ client, log, sendToCore, store = { load: () => null, save: () => {} } }) {
    this.client = client;
    this.log = log;
    this.sendToCore = sendToCore;
    this.store = store;
    const saved = store.load() ?? {};
    this.channel = saved.channel ?? null;
    this.thread = saved.thread ?? null;
    this.left = saved.left ?? false; // the core left the meeting: its last messages still go in the thread
    this.modals = new Map(); // button id -> modal descriptor, for the Edit forms
    this.catalog = [];
    this.queue = Promise.resolve();
  }

  // The core does not wait for `sent`: messages are carried out one at a time, so that the
  // first one is the thread root before the next ones answer it.
  enqueue(msg) {
    this.queue = this.queue.then(() => this.handle(msg));
    return this.queue;
  }

  async handle(msg) {
    try {
      if (msg.type === "send") await this.#send(msg);
      else if (msg.type === "join") this.#join(msg.text_channel_id);
      // The core leaves before it writes the minutes: their link still goes in the thread.
      else if (msg.type === "leave") this.#keep({ left: true });
      else if (msg.type === "modals") for (const { id, modal } of msg.modals ?? []) this.modals.set(id, modal);
      else if (msg.type === "commands") this.catalog = msg.commands ?? [];
      // `reply`: the Slack connector never creates interactions, everything reaches the core
      // as a chat line, answered with `send`.
    } catch (error) {
      const code = error.data?.error ?? error.message;
      this.log(`${msg.type} failed: ${code}`);
      this.sendToCore("error", { message: `${msg.type}: ${code}` });
    }
  }

  // The core repeats `join` until the connector reports the voice as ready, and after a
  // restart: the thread is kept as long as the channel is the same. The next meeting, even
  // in the same channel, opens its own thread.
  #join(channel) {
    if (channel !== this.channel || this.left) this.#keep({ channel, thread: null, left: false });
  }

  #keep(state) {
    Object.assign(this, state);
    this.store.save({ channel: this.channel, thread: this.thread, left: this.left });
  }

  async #send(msg) {
    const text = fitText(slackLinks(escapeMrkdwn(msg.text ?? "")));
    const blocks = [{ type: "section", text: { type: "mrkdwn", text } }];
    const buttons = msg.buttons ?? [];
    if (buttons.length) {
      blocks.push({
        type: "actions",
        elements: buttons.slice(0, 25).map((button) => ({
          type: "button",
          action_id: button.id,
          text: { type: "plain_text", text: button.label.slice(0, 75) },
          ...(button.id.endsWith(":validate") ? { style: "primary" } : {}),
        })),
      });
      for (const button of buttons) if (button.modal) this.modals.set(button.id, button.modal);
    }
    const channel = msg.channel_id ?? this.channel;
    const inThread = this.thread && channel === this.channel;
    const result = await this.client.chat.postMessage({
      channel,
      text,
      blocks,
      unfurl_links: false,
      ...(inThread ? { thread_ts: this.thread } : {}),
    });
    if (channel === this.channel && !this.thread) this.#keep({ thread: result.ts });
    this.sendToCore("sent", { request_id: msg.request_id, message_id: result.ts });
  }
}
