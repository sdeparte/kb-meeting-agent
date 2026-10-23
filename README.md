# kb-meeting-agent

An agent that joins a voice meeting, listens, and works with a knowledge base (KB) of Markdown files in a Git repository:

- answers questions about the KB when someone addresses it, and questions about the project's code ("which code handles…?") when you give it the code repositories;
- flags statements that contradict the KB, quoting the KB line verbatim;
- detects decisions, asks the participants to validate them, and opens one pull request per decision, listing the KB pages and code files it probably affects;
- opens a pull request with detailed minutes at the end of the meeting.

Models are pluggable: Claude through the Anthropic API, or any OpenAI-compatible server (Ollama, LM Studio, llama.cpp, mlx-lm) for a fully local setup.

> **Status.** The agent joins Discord voice channels and, unofficially, Slack huddles (`kb-meeting-agent run`), and can replay a recorded transcript (`kb-meeting-agent replay`).

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 22.12 or later, for the connectors
- Git
- A KB: a Git repository of Markdown files, hosted on GitHub to publish pull requests
- One of:
  - a local OpenAI-compatible server, for example [Ollama](https://ollama.com);
  - an Anthropic API key;
  - both, for example a local model for the frequent detection steps and Claude for writing.

## Setup

### 1. Install

```bash
git clone https://github.com/sdeparte/kb-meeting-agent.git
cd kb-meeting-agent
uv sync
```

### 2. Choose your models

The agent uses three model roles:

| Role | Used for | Called |
|---|---|---|
| `fast` | detecting claims, decisions and topics; understanding when it is addressed; rewriting search queries; keeping a running summary of the meeting | every ~30 s of meeting (summary every ~5 min) |
| `strong` | answering questions, comparing a claim with the KB, writing decision records and minutes | on demand |
| `embedding` | indexing the KB for semantic search | when the KB changes, and once per search |

Every call asks for a short JSON answer that matches a schema, so mid-sized local models are usable. The models below are examples, not benchmarks.

**Fully local, with Ollama**

```bash
ollama pull qwen3:14b   # fast and strong
ollama pull bge-m3      # embedding (multilingual)
```

```yaml
llm:
  fast:      { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "qwen3:14b", request_options: { reasoning_effort: "none", temperature: 0, max_tokens: 8192 } }
  strong:    { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "qwen3:14b", request_options: { reasoning_effort: "none", temperature: 0, max_tokens: 8192 } }
  embedding: { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "bge-m3" }
```

`reasoning_effort: "none"` switches off Qwen3's reasoning mode: otherwise it thinks before every answer, which turns a sub-second step into about 20 seconds. On a 16 GB machine, use `qwen3:8b` instead of `qwen3:14b`: it leaves room for live transcription.

The agent requests JSON-schema structured output (`response_format: json_schema`). If your server rejects it, the agent reports "checks paused" and the reason is in the logs; use a server version that supports structured outputs.

**Claude for the heavy steps**

```yaml
llm:
  fast:      { provider: anthropic, model: claude-haiku-5-5, api_key: "${ANTHROPIC_API_KEY}" }
  strong:    { provider: anthropic, model: claude-opus-5-5, api_key: "${ANTHROPIC_API_KEY}", effort: high, refusal_fallback: true }
  embedding: { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "bge-m3" }
```

Anthropic has no embeddings endpoint: the `embedding` role must use an OpenAI-compatible server (the configuration is rejected otherwise).

### 3. Create a GitHub token

Only needed to open real pull requests (`--publish`) or to read a private KB.

Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new) restricted to the KB repository, with these repository permissions:

- **Contents**: read and write (clone, create branches and commits)
- **Pull requests**: read and write (open pull requests, list open ones to number decisions)
- **Metadata**: read (granted automatically)

The token is passed to Git through its environment, only for `https://github.com/` URLs: it is never written to the local clone and never sent to another host.

### 4. Write `config.yml`

```bash
cp config.example.yml config.yml   # git-ignored
export ANTHROPIC_API_KEY=...       # if you use Claude
export GITHUB_TOKEN=...            # required by the example's `token:` line; remove that line for a dry run on a public KB
```

Declare a project under `projects`: its KB repository, tagged `KnowledgeBase`, and optionally code repositories, tagged `CodeBase` plus a tag of your choice (`FrontEnd`, `BackEnd`…). Values written as `${VAR}` are read from the environment. Every option is described in [docs/configuration.md](docs/configuration.md).

A code repository needs only a read-only token (Contents: read), and only when it is private. Index it once before the first meeting, which can take a while on a large repository:

```bash
uv run kb-meeting-agent index --project my-project
```

**Upgrading from `knowledge_bases`.** Each former entry becomes a project with one repository tagged `KnowledgeBase`. Before upgrading, close or `/meeting retry-publish` every pending meeting: meetings saved by the previous version can neither be resumed nor republished. The KB is cloned and indexed again under `projects/`; the former `<data_dir>/kb/` directory can then be deleted.

**Upgrading from the `discord` section.** It becomes `connector: {name: discord, env: {DISCORD_TOKEN: ..., DISCORD_GUILD_ID: ...}}`, and `connector_dir` becomes `dir` ([docs/configuration.md](docs/configuration.md#connector)). The core and `connector-discord` speak protocol v2 and must be updated together (`npm ci` in `connector-discord/`). A transcription option that the chosen engine ignores (`beam_size` on `mlx-whisper`, say) now stops the configuration from loading instead of doing nothing.

### 5. Describe your KB's conventions (optional)

Add a `.meeting-agent.yml` at the root of the KB repository to tell the agent its language, which files to skip, how decision records are named and numbered, where minutes go, and which status tags the pages use. Without it, the agent uses English and generic defaults. See [docs/configuration.md](docs/configuration.md#kb-conventions-meeting-agentyml).

## Replay a meeting

```bash
uv run kb-meeting-agent replay examples/transcript.jsonl --project my-project
```

The agent clones (or updates) the project's repositories, indexes them, then feeds the transcript to the agent segment by segment. Its messages are printed with an `[agent]` prefix, and decision buttons are shown with their ids.

| Option | Effect |
|---|---|
| `--config PATH` | configuration file (default `config.yml`) |
| `--project NAME` | project to use, as named in `config.yml` (default: `defaults.project`, or the only project) |
| `--out DIR` | output directory (default `replay-out/`) |
| `--level silent\|contradictions\|context` | how often the agent speaks up on its own (default from `config.yml`) |
| `--auto-validate` | validate every detected decision, to see the decision records it would open |
| `--publish` | open real pull requests on GitHub instead of a dry run |

**Dry run by default.** Without `--publish`, nothing is published: what would be published is written under `replay-out/<branch>/`, with a `PR.md` holding the pull request title and description.

**Output**

```
replay-out/
  transcript.jsonl                       the transcript as the agent recorded it
  decision/<date>-<slug>/...             one folder per decision record (dry run)
  meetings/<date>-<slug>/...             the minutes (dry run)
  unpublished/...                        files kept when publishing to GitHub failed
```

Branch names, and therefore these folder names, follow the KB's conventions.

### Transcript format

One JSON object per line, times in seconds from the start of the meeting:

```json
{"speaker_id": "1", "speaker_name": "Alice", "start": 15.0, "end": 24.0, "text": "Scribe, what does the KB say about the cooldown?"}
```

The agent answers when its `agent.name`, or one of its `agent.aliases`, appears in a segment (`Scribe` in the example configuration).

## Live meetings

The core joins live meetings through a **connector**: a separate process that brings the agent into a meeting platform and relays audio and chat. One connector runs at a time, chosen in `config.yml` under `connector:`. Each connector's README explains how to create its accounts and configure it:

| Platform | Connector |
|---|---|
| Discord voice channels | [connector-discord](connector-discord/README.md) |
| Slack huddles | [connector-slack](connector-slack/README.md) (unofficial: drives a dedicated account in a browser) |

### Configure transcription

```yaml
transcription:
  language: fr
  live:  { provider: mlx-whisper, model: mlx-community/whisper-large-v3-turbo }   # Mac
  final: { provider: mlx-whisper, model: mlx-community/whisper-large-v3-mlx }         # optional second pass
```

On Linux or WSL, use `provider: faster-whisper` (`model: small` on CPU, `large-v3` on a CUDA GPU). Every option is in [docs/configuration.md](docs/configuration.md#connector-and-transcription).

### Run

```bash
uv sync --extra mlx          # macOS on Apple Silicon; use --extra faster elsewhere
export GITHUB_TOKEN=... ANTHROPIC_API_KEY=...   # plus the connector's own variables
uv run kb-meeting-agent run
```

The core starts the connector and restarts it if it stops. Stop it with Ctrl+C: a running meeting is closed first.

### Commands

The same commands work on every platform. Type them in the meeting's chat; both the French and the English words are accepted, and the agent answers in the KB's language. Connectors that have slash commands and buttons (Discord, Slack) offer them too, for the same commands.

| Command | Effect |
|---|---|
| `!start [project] [level]` | start the meeting (how the agent joins depends on the platform: see its connector) |
| `!projet <name>` / `!project <name>` | change the project, only until the agent has said anything |
| `!fin` / `!end` | write the minutes and open the pull requests; the agent leaves |
| `!question <question>` / `!ask <question>` | answer from the KB and the code |
| `!niveau <level>` / `!level <level>` | `silent`, `contradictions` or `context` |
| `!optout` | stop transcribing your voice |
| `!reprendre` / `!resume` | resume the last meeting interrupted by a crash |
| `!republier` / `!retry-publish` | publish pull requests kept after a failed publication |
| `!valider dN` / `!validate dN` | validate proposed decision N (its id is in the proposal: "Decision d2 detected: …") |
| `!ignorer dN` / `!ignore dN` | ignore proposed decision N |
| `!modifier dN <statement>` / `!edit dN <statement>` | reword proposed decision N, then validate it |
| `!aide` / `!help` | list the commands |

A meeting uses `defaults.project`, or the only project when there is one; `!start <project>` names another. `!start` in a call whose meeting was interrupted by a crash today offers to resume it: `!resume` picks it up, `!start` again starts a new meeting.

Changing the project, ending the meeting, changing the level and acting on decisions are for the meeting's participants: from its call or its text channel. A `!` word that is not a command is left to other bots, except in the meeting's text channel, where it gets the help.

Participants can also address the agent by voice, by its `agent.name` ("Scribe, …"). It says at once what it is about to do ("🔎 Searching the KB: …", or drafting a validated decision), then answers in reply to that message. Every exchange with it (questions and answers, contradictions it pointed out, decisions it proposed and who validated them) is woven into the minutes, which name it "Scribe (AI)". The agent leaves when nobody is left in the meeting for `auto_leave_empty_minutes`.

**Audio and privacy.** Audio is kept on the agent's machine until the minutes are published (for the second transcription pass), then deleted. `!optout` deletes your recorded audio at once; what you said before stays in the transcript. Meeting folders are deleted after `transcript_retention_days`. The full transcript is never published. Everyone in the meeting sees the recording notice when it starts.

**Headsets.** Without one, a participant's microphone picks up the people around them, and their words end up in that participant's transcript.

**Docker (Linux, WSL, Discord only).** `docker build -t kb-meeting-agent .`, then `docker run --rm -v "$PWD/config:/config" -v "$PWD/data:/data" -e DISCORD_TOKEN -e GITHUB_TOKEN -e ANTHROPIC_API_KEY kb-meeting-agent`, with `data_dir: /data` in `config/config.yml`. The image transcribes on the CPU with faster-whisper. Stopping the container closes the running meeting first (second pass, minutes): give it time with `docker stop --time 600` (or `stop_grace_period` in Compose).

### Troubleshooting

Platform-specific problems are in each connector's README.

| Symptom | Cause |
|---|---|
| "Transcription is running N s behind" | the live engine is too slow for the machine: set `temperature_fallback: false` on `transcription.live`, then try a smaller model |
| Phrases missing when people talk over each other | compare `utterances.jsonl` and `transcript.jsonl` in the meeting folder, and `stats.jsonl` for receive errors |
| The connector is refused (core log) | the connector and the core speak different protocol versions: update both from the same checkout |

Meeting folders live in `<data_dir>/meetings/<date>-<id>/`.

## How it behaves

- **Answers** use only excerpts of the project's repositories. KB pages are cited as `path#section`, code as `[Tag] repo:path:start-end` with a link to those lines on GitHub; the agent tells what the code does apart from what the KB says. When nothing covers the question, it says so.
- **Code** is read only: it is never used to contradict a statement, and the agent never writes to a code repository.
- **Contradictions** are posted only when the model is confident, when the quoted line really exists in the cited file, and once per subject. The agent shows the full KB line, says "the KB says…" rather than "this is wrong", and warns when the page has not been verified recently.
- **Decisions** are proposed with Validate / Edit / Ignore buttons, or with the `!validate dN` / `!edit dN …` / `!ignore dN` commands to type on platforms without buttons; in a live meeting they can also be validated by voice (Edit needs a live connector: it does nothing in replay). A validated decision becomes a pull request with the record, the transcript lines it comes from (labelled as context when the exact line could not be found), the KB pages that probably need an update (not modified), and the code files it probably requires changing. If publishing fails, the files are kept under `unpublished/`.
- **Minutes** are written at the end in two passes (summaries of 10-minute slices, then a synthesis) and published as a pull request. The full transcript is never published; decision pull requests quote only the relevant lines, with speaker and time.

## Development

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
(cd connector-discord && npm test)
(cd connector-browser && npm ci && npx playwright install chromium && npm test)
(cd connector-slack && npm ci && npm test)
```

## License

Apache-2.0
