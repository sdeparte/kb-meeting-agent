// What people do on Slack, as the core expects it. Slack slash commands are fixed in the app
// manifest (`/meeting`, `/ask`), so they are passed on as the "!" line they stand for: the
// core alone parses commands.

// Slack sends `<`, `>` and `&` typed by people as HTML entities.
export function unescapeSlack(text) {
  return (text ?? "").replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&");
}

export function slashToChat(command, text) {
  const words = unescapeSlack(text).trim().split(/\s+/).filter(Boolean).join(" ");
  if (command === "/ask") return words ? `!ask ${words}` : "!ask";
  return words ? `!${words}` : "!help";
}

// A "!" line from a person: while a meeting runs, only from its channel (its thread or the
// channel itself); otherwise from any channel the app is in (`!reprendre`, `!republier`).
// A thread reply also sent to the channel (`thread_broadcast`) counts.
export function chatFromMessage(event, { meetingChannel, agentUserId }) {
  const text = unescapeSlack(event.text).trim();
  if (meetingChannel && event.channel !== meetingChannel) return null;
  if (event.subtype && event.subtype !== "thread_broadcast") return null;
  if (event.bot_id || !event.user || event.user === agentUserId) return null;
  return text.startsWith("!") ? { text, userId: event.user } : null;
}

const cut = (text, max) => (text ?? "").slice(0, max);

// The Edit form of a decision, opened when its button is clicked.
export function modalView(buttonId, modal) {
  return {
    type: "modal",
    callback_id: buttonId,
    title: { type: "plain_text", text: cut(modal.title, 24) },
    submit: { type: "plain_text", text: cut(modal.label, 24) || "OK" },
    blocks: [
      {
        type: "input",
        block_id: "value",
        label: { type: "plain_text", text: cut(modal.label, 2000) },
        element: { type: "plain_text_input", action_id: "value", multiline: true, initial_value: cut(modal.value, 3000) },
      },
    ],
  };
}

// Which call each user is in, from the `user_huddle_changed` events: the agent's own call
// leads to the channel of the huddle it joined (the members come from the huddle window).
export class Members {
  constructor() {
    this.calls = new Map(); // user id -> call id
  }

  update(event) {
    const { id, profile = {} } = event.user ?? {};
    if (!id) return;
    if (profile.huddle_state === "in_a_huddle" && profile.huddle_state_call_id) this.calls.set(id, profile.huddle_state_call_id);
    else this.calls.delete(id);
  }

  callOf(userId) {
    return this.calls.get(userId) ?? null;
  }
}
