# Manual test: a live Discord meeting

Run before merging a change to the connector, the session or the transcription.

## Setup

- A test Discord server, the bot invited (see the README), two participants with headsets.
- `config.yml` with `connector` (`name: discord`), `transcription` and a test project (a KB and a code repository, indexed with `kb-meeting-agent index`); `uv sync --extra mlx` (Mac) or `--extra faster`.
- `cd connector-discord && npm ci`, then `uv run kb-meeting-agent run --config config.yml`.

## Checklist

- [ ] The log shows `ready as …; commands registered`, then the connector's hello.
- [ ] `/meeting start project:<name>` from a voice channel: the bot joins, the notice is posted, the reply says the meeting started.
- [ ] Each participant speaks: segments appear in `<data_dir>/meetings/<id>/transcript.jsonl` with the right names, within a few seconds.
- [ ] Two people talk at the same time for 30 s: compare `utterances.jsonl` and `transcript.jsonl` with what was said; note lost phrases.
- [ ] One person talks for more than 30 s: two utterances, nothing lost.
- [ ] "<agent name>, what does the KB say about <topic>?": a sourced answer.
- [ ] "<agent name>, how does the back handle <topic>?": an answer citing `[BackEnd] back:…` with a link to the lines.
- [ ] A statement that contradicts the KB: one contradiction message quoting the KB line.
- [ ] A decision: the proposal with Validate / Edit / Ignore; Edit opens a modal prefilled with the statement; validating opens a PR; for a decision touching code, the PR lists the code files.
- [ ] `/ask`, `/meeting level silent`: replies; no more contradiction messages afterwards.
- [ ] `/meeting optout`: that person's speech no longer appears in the transcript.
- [ ] Kill the connector (`pkill -f connector-discord`): the core restarts it, the bot rejoins, "Audio was interrupted from … to …" is posted.
- [ ] Everyone leaves: the bot leaves after `auto_leave_empty_minutes` and the minutes PR is opened.
- [ ] Kill the core during a meeting, restart it, `/meeting resume`: the bot rejoins and the transcript continues.
- [ ] `stats.jsonl` has a line per minute; `decrypt_errors` stays near 0 after joining.
