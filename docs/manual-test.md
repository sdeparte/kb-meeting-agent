# Manual test: a live Discord meeting

Run before merging a change to the connector, the session or the transcription.

## Setup

- A test Discord server, the bot invited with the **Message Content Intent** on (see [connector-discord/README.md](../connector-discord/README.md)), two participants with headsets.
- `config.yml` with `connector` (`name: discord`), `transcription` and two test projects, `defaults.project` naming the first (each a KB, the first with a code repository too, indexed with `kb-meeting-agent index`); `uv sync --extra mlx` (Mac) or `--extra faster`.
- `cd connector-discord && npm ci`, then `uv run kb-meeting-agent run --config config.yml`.

## Checklist

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
