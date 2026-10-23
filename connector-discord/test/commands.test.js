import assert from "node:assert/strict";
import { test } from "node:test";

import { commandName, commandOptions, toDiscordCommands } from "../src/commands.js";

const LEVELS = ["silent", "contradictions", "context"];
const CATALOG = [
  {
    id: "meeting_start",
    slash: ["meeting", "start"],
    description: "Transcribe your voice channel",
    options: [
      { name: "project", description: "Project name", required: false, choices: [] },
      { name: "level", description: "How often the agent speaks up", required: false, choices: LEVELS },
    ],
  },
  { id: "meeting_end", slash: ["meeting", "end"], description: "End the meeting", options: [] },
  { id: "meeting_retry_publish", slash: ["meeting", "retry-publish"], description: "Publish kept PRs", options: [] },
  {
    id: "ask",
    slash: ["ask"],
    description: "Ask the agent about the project",
    options: [{ name: "question", description: "Your question", required: true, choices: [] }],
  },
];

function interaction(commandName, subcommand, strings = {}) {
  return {
    commandName,
    options: {
      getSubcommand: () => subcommand,
      getString: (name) => strings[name] ?? null,
    },
  };
}

test("the catalog becomes one meeting command with subcommands and top-level commands", () => {
  const commands = toDiscordCommands(CATALOG);
  assert.deepEqual(commands.map((c) => c.name), ["meeting", "ask"]);
  const meeting = commands[0];
  assert.equal(meeting.description, "Meeting agent");
  assert.deepEqual(meeting.options.map((o) => [o.type, o.name]), [
    [1, "start"],
    [1, "end"],
    [1, "retry-publish"],
  ]);
  const [project, level] = meeting.options[0].options;
  assert.deepEqual([project.type, project.name, project.required], [3, "project", false]);
  assert.deepEqual(level.choices, LEVELS.map((value) => ({ name: value, value })));
  const ask = commands[1];
  assert.equal(ask.description, "Ask the agent about the project");
  assert.deepEqual([ask.options[0].name, ask.options[0].required], ["question", true]);
  assert.equal(ask.options[0].choices, undefined);
});

test("command names map to catalog ids", () => {
  assert.equal(commandName(interaction("meeting", "start")), "meeting_start");
  assert.equal(commandName(interaction("meeting", "retry-publish")), "meeting_retry_publish");
  assert.equal(commandName(interaction("ask", null)), "ask");
});

test("options are the command's catalog options, null when absent", () => {
  const options = commandOptions(interaction("meeting", "start", { level: "context" }), CATALOG);
  assert.deepEqual(options, { project: null, level: "context" });
  assert.deepEqual(commandOptions(interaction("meeting", "end"), CATALOG), {});
});
