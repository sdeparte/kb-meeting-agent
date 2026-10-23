// The meeting's chat: Meet shows text only, so the core writes the commands to type under its
// decisions (the hello says `buttons: false`). Long messages are split to Meet's length.
export const MEET_CHAT_MAX = 500; // characters per Meet chat message

export function splitForChat(text, max = MEET_CHAT_MAX) {
  const parts = [];
  let rest = (text ?? "").trim();
  while (rest.length > max) {
    const window = rest.slice(0, max + 1);
    let cut = window.lastIndexOf("\n");
    if (cut <= 0) cut = window.lastIndexOf(" ");
    const hard = cut <= 0; // one word longer than the limit
    if (hard) cut = max;
    parts.push(rest.slice(0, cut).trim());
    rest = rest.slice(hard ? cut : cut + 1).trim();
  }
  if (rest) parts.push(rest);
  return parts.filter(Boolean);
}

// The core writes Markdown links; Meet's chat shows plain text (and links the bare URLs).
export function plainLinks(text) {
  return (text ?? "").replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, "$1 ($2)");
}

// A "!" line someone else typed: a command for the core.
export function chatLine({ text, self }) {
  const line = (text ?? "").trim();
  return !self && line.startsWith("!") ? { text: line } : null;
}

export class Outbound {
  constructor({ ui, page, currentCode, sendToCore, log }) {
    Object.assign(this, { ui, page, currentCode, sendToCore, log });
    this.queue = Promise.resolve();
    this.count = 0;
  }

  // The core does not wait for `sent`: messages are posted one at a time, in order.
  enqueue(msg) {
    this.queue = this.queue.then(() => this.#handle(msg));
    return this.queue;
  }

  // `modals`, `reply` and `commands` mean nothing without buttons or slash commands.
  async #handle(msg) {
    if (msg.type !== "send") return;
    const code = this.currentCode();
    if (!code || (msg.channel_id && msg.channel_id !== code)) {
      this.log("dropping a message: the agent is not in that meeting");
      return;
    }
    try {
      for (const part of splitForChat(plainLinks(msg.text))) await this.ui.sendChat(this.page, part);
      this.count += 1;
      this.sendToCore("sent", { request_id: msg.request_id, message_id: `meet-${this.count}` });
    } catch (error) {
      this.log(`send failed: ${error.message}`);
      this.sendToCore("error", { message: `send: ${error.message}` });
    }
  }
}
