# Manual tests: live meetings

Run before merging a change to the connector, the session or the transcription.

## Discord: setup

- A test Discord server, the bot invited with the **Message Content Intent** on (see [connector-discord/README.md](../connector-discord/README.md)), two participants with headsets.
- `config.yml` with `connector` (`name: discord`), `transcription` and two test projects, `defaults.project` naming the first (each a KB, the first with a code repository too, indexed with `kb-meeting-agent index`); `uv sync --extra mlx` (Mac) or `--extra faster`.
- `cd connector-discord && npm ci`, then `uv run kb-meeting-agent run --config config.yml`.

## Discord: checklist

- [ ] The log shows `ready as …`, then `commands registered`; `/meeting` and `/ask` appear in Discord.
- [ ] `!start` typed in the voice channel's chat: the bot joins, the notice names the default project, and the start message is posted in the chat.
- [ ] `!project <second>` right away: the notice is posted again for the second project. After the agent has answered something, `!project <first>` is refused.
- [ ] `!help` lists the commands in the KB's language; `!nope` in the meeting's text channel gets the same help; `!nope` in another voice channel's chat and a sentence without `!` get nothing.
- [ ] Each participant speaks: segments appear in `<data_dir>/meetings/<id>/transcript.jsonl` with the right names, within a few seconds.
- [ ] Two people talk at the same time for 30 s: compare `utterances.jsonl` and `transcript.jsonl` with what was said; note lost phrases.
- [ ] One person talks for more than 30 s: two utterances, nothing lost.
- [ ] "<agent name>, what does the KB say about <topic>?": a sourced answer.
- [ ] "<agent name>, how does the back handle <topic>?": an answer citing `[BackEnd] back:…` with a link to the lines.
- [ ] A statement that contradicts the KB: one contradiction message quoting the KB line.
- [ ] A decision: the proposal with Validate / Edit / Ignore; Edit opens a modal prefilled with the statement; validating opens a PR; for a decision touching code, the PR lists the code files.
- [ ] The proposal shows the decision's id; `!validate dN` and `!edit dN <statement>` typed in the chat do what the buttons do; `!validate d99` lists the pending decisions; `!project <second>` typed in another voice channel's chat is refused.
- [ ] `/ask` and `!question`, `/meeting level silent` and `!level silent`: replies; no more contradiction messages afterwards.
- [ ] `/meeting optout`: that person's speech no longer appears in the transcript.
- [ ] Kill the connector (`pkill -f connector-discord`): the core restarts it, the bot rejoins, "Audio was interrupted from … to …" is posted.
- [ ] Everyone leaves: the bot leaves after `auto_leave_empty_minutes` and the minutes PR is opened.
- [ ] Kill the core during a meeting, restart it, `!start` from the same voice channel: the agent offers to resume; `!resume` resumes the meeting (not a new one), the notice is posted again and the transcript continues.
- [ ] `stats.jsonl` has a line per minute; `decrypt_errors` stays near 0 after joining.

## Slack huddle

Setup: the app installed and invited into a test channel, the agent's account signed in with `npm run login`, `connector: {name: slack, …}` as in [connector-slack/README.md](../connector-slack/README.md). Run first with `SLACK_HEADLESS=false` to watch the browser.

- [ ] The log shows `ready: waiting for huddle invitations`.
- [ ] Start a huddle in the channel and invite the agent's account: it joins within a few seconds, a thread opens in the channel with the notice and the project.
- [ ] Two people speak in turn: `transcript.jsonl` has their names, not "Unknown"; `stats.jsonl` keeps `unknown_frames` low.
- [ ] `/meeting aide` and `!aide` in the thread list the commands; `/ask …` gets an answer in the thread.
- [ ] A decision: Validate / Edit / Ignore buttons; Edit opens a form prefilled with the statement.
- [ ] `!projet <second>` before the agent speaks changes the project; after, it is refused.
- [ ] `!optout`: that person's speech stops appearing, including when they talk over someone.
- [ ] Invite the account into a second huddle meanwhile: ignored (log line), the first one continues. After a connector restart, invite it into a huddle of another channel first: it leaves it, nothing is recorded.
- [ ] After the meeting, `!republier` typed in the channel reaches the agent.
- [ ] Kill the connector (`pkill -f connector-slack`): the core restarts it; the agent asks in the thread to be invited again; invite the account: the same meeting resumes in the same thread (no new start), "Audio was interrupted from … to …" is posted.
- [ ] Remove the account from the huddle: the agent asks to be invited again; invite it back: the meeting goes on, with an "Audio was interrupted" notice. Remove it and leave it out: the minutes are published after `auto_leave_empty_minutes`.
- [ ] `!optout`, then someone else speaks while the opted-out person starts talking: none of the opted-out person's words appear, under any name.
- [ ] Sign the profile out (delete its folder): the log asks for `npm run login`, the connector does not restart faster than once a minute.

## Google Meet

Setup: the agent's Google account signed in with `npm run login`, its calendar adding invitations automatically, `connector: {name: meet, …}` as in [connector-meet/README.md](../connector-meet/README.md). Run first with `MEET_HEADLESS=false`.

- [ ] The log shows `ready: watching the calendar for invited meetings`.
- [ ] Invite the agent's address to a meeting starting in 3 minutes: it joins about a minute before, its microphone and camera off; admit it if asked.
- [ ] The chat shows the notice with the project; `!aide` lists the commands.
- [ ] Two people speak in turn: their names in `transcript.jsonl`, few "Unknown".
- [ ] `!ask …`: the answer is in the chat, split if long.
- [ ] A decision: the message ends with the commands to type; `!valider d1` publishes it, `!modifier d2 …` rewords then publishes.
- [ ] `!projet <second>` before the agent speaks changes the project; after, it is refused.
- [ ] `!optout` from the chat: that person's speech stops appearing.
- [ ] Kill the connector (`pkill -f connector-meet`): the core restarts it, the agent rejoins the meeting still in progress and the meeting resumes.
- [ ] `!fin`: the agent leaves, the minutes are published, and it does not come back to that meeting.
- [ ] Do not admit it on another meeting: after `MEET_ADMISSION_TIMEOUT_SECONDS` the log says `not admitted to …` and it does not retry.
- [ ] Decline an invitation from the agent's calendar: it does not join.
- [ ] An invitation from an account outside `MEET_ALLOWED_ORGANIZERS`: it does not join.
- [ ] Cut the agent's network for 10 s mid-meeting: it rejoins; then `!fin`: it does not come back.
- [ ] Someone who typed `!optout` leaves and rejoins the call: their speech still does not appear (Meet gives them a new participant id).
