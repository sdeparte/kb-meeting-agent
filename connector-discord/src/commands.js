// Discord slash commands built from the core's command catalog (the `commands` message).
const SUBCOMMAND = 1;
const STRING = 3;
const GROUP_DESCRIPTIONS = { meeting: "Meeting agent" };

function toOption(option) {
  return {
    type: STRING,
    name: option.name,
    description: option.description.slice(0, 100),
    required: option.required,
    ...(option.choices.length ? { choices: option.choices.map((value) => ({ name: value, value })) } : {}),
  };
}

export function toDiscordCommands(catalog) {
  const commands = new Map();
  for (const entry of catalog) {
    const [top, sub] = entry.slash;
    if (sub === undefined) {
      commands.set(top, { name: top, description: entry.description.slice(0, 100), options: entry.options.map(toOption) });
      continue;
    }
    if (!commands.has(top)) commands.set(top, { name: top, description: GROUP_DESCRIPTIONS[top] ?? top, options: [] });
    commands.get(top).options.push({
      type: SUBCOMMAND,
      name: sub,
      description: entry.description.slice(0, 100),
      options: entry.options.map(toOption),
    });
  }
  return [...commands.values()];
}

export function commandName(interaction) {
  const sub = interaction.options.getSubcommand(false);
  return sub ? `${interaction.commandName}_${sub.replaceAll("-", "_")}` : interaction.commandName;
}

export function commandOptions(interaction, catalog) {
  const entry = catalog.find((c) => c.id === commandName(interaction));
  return Object.fromEntries((entry?.options ?? []).map((o) => [o.name, interaction.options.getString(o.name)]));
}
