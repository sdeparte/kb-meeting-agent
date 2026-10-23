import assert from "node:assert/strict";
import { test } from "node:test";

import { COMMANDS, commandName, commandOptions } from "../src/commands.js";

function interaction(commandName, subcommand, strings = {}) {
  return {
    commandName,
    options: {
      getSubcommand: () => subcommand,
      getString: (name) => strings[name] ?? null,
    },
  };
}

test("command names map to protocol names", () => {
  assert.equal(commandName(interaction("meeting", "start")), "meeting_start");
  assert.equal(commandName(interaction("meeting", "retry-publish")), "meeting_retry_publish");
  assert.equal(commandName(interaction("ask", null)), "ask");
});

test("options are read by name", () => {
  const options = commandOptions(interaction("meeting", "start", { project: "cyberhack", level: "silent" }));
  assert.deepEqual(options, { project: "cyberhack", level: "silent", question: null });
});

test("every meeting subcommand is declared", () => {
  const meeting = COMMANDS.find((c) => c.name === "meeting");
  assert.deepEqual(meeting.options.map((o) => o.name), ["start", "end", "level", "optout", "resume", "retry-publish"]);
});
