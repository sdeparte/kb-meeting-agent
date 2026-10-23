import assert from "node:assert/strict";
import { test } from "node:test";

import { Members, chatFromMessage, modalView, slashToChat } from "../src/inbound.js";

test("slash commands become the matching ! line", () => {
  assert.equal(slashToChat("/meeting", "fin"), "!fin");
  assert.equal(slashToChat("/meeting", "  projet  cyberhack "), "!projet cyberhack");
  assert.equal(slashToChat("/meeting", ""), "!help");
  assert.equal(slashToChat("/ask", "quel cooldown ?"), "!ask quel cooldown ?");
  assert.equal(slashToChat("/ask", ""), "!ask");
  assert.equal(slashToChat("/ask", "a &lt; b &amp;&amp; c &gt; d ?"), "!ask a < b && c > d ?");
});

const where = { meetingChannel: "C1", agentUserId: "UAGENT" };
const event = (fields) => ({ channel: "C1", user: "U1", text: "!fin", ...fields });

test("! lines from people in the meeting channel go to the core", () => {
  assert.deepEqual(chatFromMessage(event({}), where), { text: "!fin", userId: "U1" });
  assert.deepEqual(chatFromMessage(event({ text: "  !ask x ", thread_ts: "1.2" }), where), { text: "!ask x", userId: "U1" });
  assert.deepEqual(chatFromMessage(event({ subtype: "thread_broadcast" }), where), { text: "!fin", userId: "U1" });
  assert.deepEqual(chatFromMessage(event({ text: "!ask a &lt; b" }), where), { text: "!ask a < b", userId: "U1" });
});

test("with no meeting running, ! lines come from any channel the app is in", () => {
  const idle = { meetingChannel: null, agentUserId: "UAGENT" };
  assert.deepEqual(chatFromMessage(event({ channel: "C2", text: "!republier" }), idle), { text: "!republier", userId: "U1" });
});

test("other channels, bots, the agent, edits and plain lines do not", () => {
  assert.equal(chatFromMessage(event({ channel: "C2" }), where), null);
  assert.equal(chatFromMessage(event({ bot_id: "B1" }), where), null);
  assert.equal(chatFromMessage(event({ user: "UAGENT" }), where), null);
  assert.equal(chatFromMessage(event({ subtype: "message_changed" }), where), null);
  assert.equal(chatFromMessage(event({ text: "on finit ?" }), where), null);
});

test("the Edit form is prefilled and within Slack's limits", () => {
  const view = modalView("decision:d1:edit", { title: "Edit the decision record now", label: "Decision as it should read", value: "x".repeat(4000) });
  assert.equal(view.type, "modal");
  assert.equal(view.callback_id, "decision:d1:edit");
  assert.ok(view.title.text.length <= 24 && view.submit.text.length <= 24);
  const [block] = view.blocks;
  assert.equal(block.block_id, "value");
  assert.equal(block.element.action_id, "value");
  assert.equal(block.element.multiline, true);
  assert.equal(block.element.initial_value.length, 3000);
});

const huddle = (id, state, call, name = id) => ({
  user: { id, real_name: name, profile: { huddle_state: state, huddle_state_call_id: call, display_name: name } },
});

test("each user's call follows their huddle state", () => {
  const members = new Members();
  members.update(huddle("UAGENT", "in_a_huddle", "R1", "Scribe"));
  members.update(huddle("U2", "in_a_huddle", "R2", "Bob"));
  assert.equal(members.callOf("UAGENT"), "R1");
  assert.equal(members.callOf("U2"), "R2");
  members.update(huddle("UAGENT", "default_unset", ""));
  assert.equal(members.callOf("UAGENT"), null);
});
