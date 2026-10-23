# connector-discord

Brings kb-meeting-agent into a **Discord voice channel**. The connector joins the channel, receives each speaker's voice separately, and relays the agent's messages, buttons and forms in the text chat. It holds no meeting logic: the core (`uv run kb-meeting-agent run`) starts it, decides everything, and sends it the commands to offer.

Speakers are told apart exactly: Discord sends one audio stream per person.

## Requirements

- Node.js 22.12 or later (the core starts the connector with it).
- A Discord server where you can add a bot.
- The core set up as in the [main README](../README.md) (models, project, `transcription`).

## 1. Create the bot

1. At <https://discord.com/developers/applications>, create an application.
2. **Bot** tab:
   - **Reset Token** and keep the token;
   - turn **Public Bot** off;
   - under **Privileged Gateway Intents**, turn **Message Content Intent** on. The connector asks for it to read the `!` commands typed in the chat (`!end`, `!ask …`): without it, Discord refuses the connector's login ("Used disallowed intents") and the core keeps restarting it. **Upgrading from an earlier version: turn it on before restarting the agent.**
3. **OAuth2 → URL Generator**: scopes `bot` and `applications.commands`; permissions *View Channels*, *Send Messages*, *Read Message History*, *Connect*, *Use Application Commands*. Open the URL and add the bot to your server.
4. Check the voice channels you will use: a channel or category override that denies **Connect** to the bot's role blocks the voice connection without a clear error.
5. In Discord, enable developer mode (Settings → Advanced), right-click the server → **Copy Server ID**.

## 2. Configure

In the core's `config.yml`:

```yaml
connector:
  name: discord
  env:
    DISCORD_TOKEN: "${DISCORD_TOKEN}"
    DISCORD_GUILD_ID: "123456789012345678"   # the server ID copied above
```

| Variable | Meaning |
|---|---|
| `DISCORD_TOKEN` | the bot token |
| `DISCORD_GUILD_ID` | the server the agent serves: slash commands are registered there, and commands from any other server are ignored |

`connector.node` (Node executable) and `connector.dir` (where this folder is) are described in [docs/configuration.md](../docs/configuration.md#connector). The connector receives only these variables and the local link to the core, never model keys or repository tokens.

## 3. Install and run

```bash
(cd connector-discord && npm ci)
export DISCORD_TOKEN=...
uv run kb-meeting-agent run
```

The core starts the connector, sends it the command catalog (registered as slash commands on the server), and restarts it if it stops.

## 4. Hold a meeting

Join a voice channel, then type `!start` in the channel's chat, or use `/meeting start` (a bot cannot be invited into a voice channel). The agent joins, posts the recording notice and the project it uses. Every command of the [common command table](../README.md#commands) works as a `!` line typed in the voice channel's own chat, or in the text channel the meeting posts to; `!` lines in other channels are left to other bots. Discord also offers them as slash commands (`/meeting end`, `/ask`, …), and decisions come with **Validate / Edit / Ignore** buttons.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `403 Missing Access (50001)` at startup | the bot is not on the server given by `DISCORD_GUILD_ID` (in `connector.env`) |
| The bot never joins; "voice connection timed out" | a channel or category override denies *Connect* |
| "Used disallowed intents" at startup, the connector restarts in a loop | **Message Content Intent** is off: turn it on (step 1) |
| `!` commands are ignored, slash commands work | the line was typed in another channel than the voice channel's chat or the meeting's text channel |
| "Unknown Integration" on a command | Discord cached old command ids: reload Discord (Ctrl+R) |
| No slash commands at all | the core is not running or refused the connector (see the core's log: protocol version) |
