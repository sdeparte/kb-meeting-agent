const STRING = 3;
const SUBCOMMAND = 1;
const LEVELS = ["silent", "contradictions", "context"].map((value) => ({ name: value, value }));

export const COMMANDS = [
  {
    name: "meeting",
    description: "Meeting agent",
    options: [
      {
        type: SUBCOMMAND,
        name: "start",
        description: "Transcribe your voice channel",
        options: [
          { type: STRING, name: "kb", description: "Knowledge base name", required: true },
          { type: STRING, name: "level", description: "How often the agent speaks up", required: false, choices: LEVELS },
        ],
      },
      { type: SUBCOMMAND, name: "end", description: "End the meeting and publish the minutes" },
      {
        type: SUBCOMMAND,
        name: "level",
        description: "Change how often the agent speaks up",
        options: [{ type: STRING, name: "level", description: "Level", required: true, choices: LEVELS }],
      },
      { type: SUBCOMMAND, name: "optout", description: "Stop transcribing your voice" },
      { type: SUBCOMMAND, name: "resume", description: "Resume the last unfinished meeting" },
      { type: SUBCOMMAND, name: "retry-publish", description: "Publish pull requests kept after a failure" },
    ],
  },
  {
    name: "ask",
    description: "Ask the agent about the knowledge base",
    options: [{ type: STRING, name: "question", description: "Your question", required: true }],
  },
];

export function commandName(interaction) {
  const sub = interaction.options.getSubcommand(false);
  return sub ? `${interaction.commandName}_${sub.replaceAll("-", "_")}` : interaction.commandName;
}

export function commandOptions(interaction) {
  return {
    kb: interaction.options.getString("kb"),
    level: interaction.options.getString("level"),
    question: interaction.options.getString("question"),
  };
}
