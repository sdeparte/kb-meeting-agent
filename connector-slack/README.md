# connector-slack

Brings kb-meeting-agent into a **Slack huddle**. Invite the agent's account into a huddle: it joins, and the meeting starts. The agent posts in a thread of the huddle's channel, with real buttons and forms, and leaves on `/meeting fin` (or `!fin`) or when everyone has left.

The connector holds no meeting logic: the core (`uv run kb-meeting-agent run`) starts it and decides everything. It uses two Slack identities:

- **a Slack app** (official API, Socket Mode): the agent's messages, buttons and forms, the `/meeting` and `/ask` commands, and who is in which huddle;
- **a dedicated Slack user account for the agent**, signed in once in a Chromium profile and driven by the connector, which joins huddles to hear them. Slack has no API for a bot to join a huddle or receive its audio.

## Read this first: limits

- **Unofficial, and against Slack's terms.** Driving a user account with a browser is not allowed by Slack's terms of service. Use it at your own risk, ideally on a workspace you administer.
- **Fragile.** It depends on Slack's web client. When Slack changes it, the connector may stop seeing invitations or speakers: the selectors to fix are all in [`src/ui.js`](src/ui.js), and [docs/manual-test.md](../docs/manual-test.md) has the checklist to verify them.
- **Speakers come from the huddle's "speaking" indicator.** The browser receives one mixed audio stream, not one per person. The audio goes to the person shown speaking; when two people talk at once, to the one who started first; when nobody is shown, to "Unknown" (a speaker keeps it for 0.4 s when the indicator flickers). Expect more attribution errors than on Discord.
- **Opt-out.** After `!optout`, audio is dropped whenever that person is shown speaking, and for one second after: what someone else says at the same moment is lost too, so that the person who opted out is never transcribed under another name. Once anyone has opted out, audio nobody is shown speaking is dropped as well (it could be their first words, before the indicator shows them): speech the indicator misses is lost for the rest of the meeting. The opt-out ends with the meeting.
- **One meeting at a time**, one connector per agent instance. Invited into another huddle while in one, the account ignores the invitation. While a meeting runs, a huddle the account joins whose channel cannot be confirmed as the meeting's (another channel, a DM, a channel the app is not in) is left at once and never recorded.

## Requirements

- Node.js 22.12 or later, and Chromium for Playwright: `npx playwright install chromium` (in `connector-browser`).
- A Slack workspace where huddles can have more than two people (Slack's free plan limits huddles to two, the agent included).
- A **dedicated Slack account** for the agent (for example `scribe@your-domain`), member of the channels where you hold huddles. Without SSO or two-factor prompts at each sign-in, if your workspace allows it.
- The core set up as in the [main README](../README.md) (models, project, `transcription`).

## 1. Create the Slack app

1. At <https://api.slack.com/apps>: **Create New App → From a manifest**, pick the workspace, paste [`manifest.yml`](manifest.yml).
2. **Basic Information → App-Level Tokens → Generate Token and Scopes**: scope `connections:write`. Keep the `xapp-…` token: `SLACK_APP_TOKEN`.
3. **Install App → Install to Workspace**. Keep the **Bot User OAuth Token** (`xoxb-…`): `SLACK_BOT_TOKEN`.
4. Invite the app into each channel where huddles will be held (`/invite @kb-meeting-agent`). The connector finds a huddle's channel through the app: without it in the channel, the agent joins but cannot start the meeting.

## 2. Prepare the agent's account

1. Create the account, add it to the channels.
2. Its member ID: open its profile → **⋮ → Copy member ID** (`U…`): `SLACK_AGENT_USER_ID`.
3. Sign it in once in the connector's browser profile:

```bash
(cd connector-browser && npm ci && npx playwright install chromium)
(cd connector-slack && npm ci)
cd connector-slack
SLACK_WORKSPACE_URL=https://your-workspace.slack.com SLACK_BROWSER_PROFILE=~/.local/share/kb-meeting-agent/slack-profile npm run login
```

A Chromium window opens: sign in with the agent's account, wait until Slack is open, close the window. The session is kept in the profile folder: keep it private, it is a signed-in Slack session. Run `npm run login` again when Slack signs the account out.

## 3. Configure

In the core's `config.yml`:

```yaml
connector:
  name: slack
  env:
    SLACK_BOT_TOKEN: "${SLACK_BOT_TOKEN}"
    SLACK_APP_TOKEN: "${SLACK_APP_TOKEN}"
    SLACK_AGENT_USER_ID: "U0123ABCD"
    SLACK_WORKSPACE_URL: "https://your-workspace.slack.com"
    SLACK_BROWSER_PROFILE: "/Users/you/.local/share/kb-meeting-agent/slack-profile"
```

| Variable | Meaning |
|---|---|
| `SLACK_BOT_TOKEN` | the app's bot token (`xoxb-…`) |
| `SLACK_APP_TOKEN` | the app-level token with `connections:write` (`xapp-…`), for Socket Mode: no public URL is needed |
| `SLACK_AGENT_USER_ID` | the agent account's member ID: never counted as a speaker or a participant |
| `SLACK_WORKSPACE_URL` | the workspace's web address |
| `SLACK_BROWSER_PROFILE` | the profile folder signed in with `npm run login` (an absolute path) |
| `SLACK_HEADLESS` | `false` to watch the browser while debugging (default `true`) |

The connector receives only these variables and the local link to the core, never model keys or repository tokens.

## 4. Hold a meeting

1. Start the agent: `uv run kb-meeting-agent run`.
2. Start a huddle in a channel where the app is, and invite the agent's account. It joins, opens a thread in the channel with the recording notice and the project used.
3. Use the [common commands](../README.md#commands): as `!` lines in the thread (or the channel; with no meeting running, in any channel the app is in, e.g. `!republier`), or as `/meeting <command>` (`/meeting fin`, `/meeting projet autre`, `/meeting aide`) and `/ask <question>`. Decisions come with **Validate / Edit / Ignore** buttons.
4. `/meeting fin` or `!fin` ends the meeting: the minutes are published. Removed from the huddle, or everyone gone, the account stops hearing and the agent asks in the thread to be invited again; invited back, it resumes the meeting in the same thread, otherwise the meeting ends after `auto_leave_empty_minutes` (5 by default).

## Troubleshooting

| Symptom | Cause |
|---|---|
| Log: `the Slack browser profile is not logged in` | run `npm run login` again |
| Inviting the account does nothing | the invitation prompt changed: check `SELECTORS.invite` in `src/ui.js` with `SLACK_HEADLESS=false` |
| Log: `left a huddle whose channel is unknown` | the app is not in that channel: `/invite @kb-meeting-agent` |
| The transcript is empty, or everything is "Unknown" | the speaking indicator changed (`SELECTORS.participant`, `speakingClass` in `src/ui.js`); `stats.jsonl` shows `unknown_frames` |
| `/meeting` answers "dispatch_failed" | the connector is not running, or the app's Socket Mode token is wrong |
| `not_in_channel` in the core's log | invite the app into the channel |
| The agent asks in the thread to be invited again | the connector restarted, or the account left the huddle: invite it again, the meeting resumes |
| `/meeting start` answers "join a voice channel first" | it was typed outside the huddle's channel: invite the account into the huddle instead |
