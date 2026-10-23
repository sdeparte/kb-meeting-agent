# connector-meet

Brings kb-meeting-agent into **Google Meet** meetings. Give the agent its own Google account, then invite that account's address to a meeting in Google Calendar, as you would invite a colleague: at the meeting's time the agent joins (asking to be admitted if needed), transcribes, and talks in the meeting chat. It leaves on `!fin`, when everyone has left, or when the call ends. If it drops out of the call (network, restart), it comes back to the same meeting by itself.

The connector holds no meeting logic: the core (`uv run kb-meeting-agent run`) starts it and decides everything. Google offers no generally available API to hear a Meet call live, so the connector drives the agent's account in a Chromium browser.

## Read this first: limits

- **Unofficial and fragile.** It depends on Meet's web client. When Google changes it, the connector may stop joining, hearing speakers or reading the chat: the selectors to fix are all in [`src/ui.js`](src/ui.js), and [docs/manual-test.md](../docs/manual-test.md) has the checklist to verify them.
- **Text only.** Meet's chat has no buttons: under each proposed decision, the agent writes what to type (`!valider d1`, `!ignorer d1`, `!modifier d1 <énoncé>`). Long answers are split into several chat messages.
- **Speakers come from Meet's "speaking" indicator.** The browser receives one mixed audio stream. The audio goes to the person shown speaking (the one who started first on overlap, kept 0.4 s through indicator flicker), to "Unknown" otherwise. Expect more attribution errors than on Discord. People are told apart by Meet's participant ids; if Meet ever stops exposing them, two people with the same name are merged.
- **Opt-out.** After `!optout`, audio is dropped whenever that person is shown speaking, and for one second after, so they are never transcribed under another name. It follows them by name, since Meet gives someone who rejoins a new participant id: participants who share their name are opted out too. Once anyone has opted out, audio that cannot be credited to someone shown speaking is dropped rather than transcribed as "Unknown". In a large call, or during a screen share, Meet hides many tiles: those people's speech is then lost for the rest of the meeting.
- **Who can bring it in.** Anyone can invite an address to a calendar event, and the agent answers in the meeting from the project's knowledge base. So it only joins events organized by the addresses or domains of `MEET_ALLOWED_ORGANIZERS`, and an event's organizer is whoever created it.
- **Calendar.** The agent joins events of its calendar that carry a Meet link and an allowed organizer, from one minute before their start until their end. Meetings it left on purpose (`!fin`, the call ended, removed by the host, not admitted within 10 minutes) are not rejoined; after a crash it goes back and the meeting resumes (if the core itself restarted, the agent first offers it in the chat: `!reprendre` resumes it). Events repeating more often than daily are ignored, and an event whose recurrence cannot be expanded within 2 seconds is skipped until the connector restarts.
- **One meeting at a time**, one connector per agent instance: of two overlapping meetings, the agent attends the one that starts first, and joins no other meeting until that one is closed. If nobody lets it back into its meeting after a drop, that meeting is closed and its minutes published.
- **The minutes link is not posted in Meet's chat**: the agent leaves the call first, then writes the minutes. The pull requests are on the repository as usual.
- **Members.** Meet only draws the tiles on screen; the agent counts everyone it has seen during the call, and the call as empty when Meet's own count says only the agent is left.

## Requirements

- Node.js 22.12 or later, and Chromium for Playwright: `npx playwright install chromium` (in `connector-browser`).
- A **dedicated Google account** for the agent. A Gmail account works. In a Google Workspace domain, meetings may refuse external guests or keep them in the lobby: someone admits the agent, or the domain allows it.
- The core set up as in the [main README](../README.md) (models, project, `transcription`).

## 1. Prepare the agent's Google account

1. Create the account (for example `scribe.yourteam@gmail.com`): `MEET_AGENT_EMAIL`.
2. In [Google Calendar](https://calendar.google.com/) with that account: **Settings → Event settings → Add invitations to my calendar**: *Only if the sender is known* when you invite it from known accounts, else *From everyone*. Invitations then appear in its calendar without being accepted by hand. Either way, only the organizers in `MEET_ALLOWED_ORGANIZERS` bring it into a meeting.
3. **Settings → Settings for my calendars → (the agent's calendar) → Integrate calendar → Secret address in iCal format**: copy it, this is `MEET_CALENDAR_ICS_URL`. It is a secret: anyone with it reads the calendar. **Reset** makes a new one (update the configuration then). The connector never writes it in its logs.
4. Sign the account in once in the connector's browser profile:

```bash
(cd connector-browser && npm ci && npx playwright install chromium)
(cd connector-meet && npm ci)
cd connector-meet
MEET_BROWSER_PROFILE=~/.local/share/kb-meeting-agent/meet-profile npm run login
```

A Chromium window opens on Google's sign-in page: sign in with the agent's account (answer the security prompts), then close the window. The session is kept in the profile folder: keep it private, it is a signed-in Google session. Run `npm run login` again when Google signs the account out.

## 2. Configure

In the core's `config.yml`:

```yaml
connector:
  name: meet
  env:
    MEET_CALENDAR_ICS_URL: "${MEET_CALENDAR_ICS_URL}"
    MEET_AGENT_EMAIL: "scribe.yourteam@gmail.com"
    MEET_BROWSER_PROFILE: "/Users/you/.local/share/kb-meeting-agent/meet-profile"
    MEET_ALLOWED_ORGANIZERS: "@yourteam.com, alice@gmail.com"
```

| Variable | Default | Meaning |
|---|---|---|
| `MEET_CALENDAR_ICS_URL` | (required) | the calendar's secret iCal address |
| `MEET_AGENT_EMAIL` | (required) | the agent's address: invitations it declined are not joined |
| `MEET_BROWSER_PROFILE` | (required) | the profile folder signed in with `npm run login` (an absolute path); the meetings left on purpose are remembered there too |
| `MEET_ALLOWED_ORGANIZERS` | (required) | who may bring the agent into a meeting: the events' organizers, as addresses or whole domains (`@yourteam.com`), comma-separated |
| `MEET_JOIN_EARLY_SECONDS` | `60` | how long before a meeting's start the agent joins |
| `MEET_ADMISSION_TIMEOUT_SECONDS` | `600` | how long it waits in the lobby before giving up on that meeting |
| `MEET_HEADLESS` | `true` | `false` to watch the browser while debugging |

The connector receives only these variables and the local link to the core, never model keys or repository tokens.

## 3. Hold a meeting

1. Start the agent: `uv run kb-meeting-agent run`.
2. In Google Calendar, invite the agent's address to a meeting with a Meet link (or add a Meet link to an event it is invited to).
3. At the meeting's time the agent joins; admit it if Meet asks. It posts the recording notice and the project in the chat.
4. Use the [common commands](../README.md#commands) as `!` lines in the chat: `!aide`, `!ask <question>`, `!projet <nom>` (before the agent has spoken), `!valider d1`, `!optout`, `!fin`.
5. `!fin`, everyone leaving, or ending the call for everyone ends the meeting: the minutes are published (the link is not posted in Meet's chat, see the limits).

## Troubleshooting

| Symptom | Cause |
|---|---|
| Log: `the Meet browser profile is not logged in` | run `npm run login` again |
| Log: `could not read the calendar: the calendar answered 404` | the secret address was reset: copy the new one |
| The agent never joins | the event's organizer is not in `MEET_ALLOWED_ORGANIZERS`, the event has no Meet link, the agent declined it, the invitation is not in its calendar (step 1.2), or the agent already left it on purpose |
| Log: `not admitted to …` | nobody admitted it within `MEET_ADMISSION_TIMEOUT_SECONDS`, or it was refused |
| Joins but the chat stays silent, or commands are ignored | the chat selectors changed (`SELECTORS.openChat`, `chatInput`, `message` in `src/ui.js`); watch with `MEET_HEADLESS=false` |
| Everything is "Unknown" in the transcript | the speaking indicator changed (`SELECTORS.tile`, `speakingClass`); `stats.jsonl` shows `unknown_frames` |
