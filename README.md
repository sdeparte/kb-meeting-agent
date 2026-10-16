# kb-meeting-agent

An agent that joins a voice meeting, listens, and works with a knowledge base (KB) of Markdown files in a Git repository:

- answers questions about the KB when someone addresses it;
- flags statements that contradict the KB, quoting the KB line verbatim;
- detects decisions, asks the participants to validate them, and opens one pull request per decision;
- opens a pull request with detailed minutes at the end of the meeting.

Models are pluggable: Claude through the Anthropic API, or any OpenAI-compatible server (Ollama, LM Studio, llama.cpp, mlx-lm) for a fully local setup.

> **Status.** The core runs in **replay** mode: it reads a recorded transcript instead of a live meeting. The Discord connector and live transcription are not implemented yet; this README will explain how to add the agent to a Discord channel once they are.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
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
  fast:      { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "qwen3:14b" }
  strong:    { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "qwen3:14b" }
  embedding: { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "bge-m3" }
```

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

Declare your KB under `knowledge_bases` (`repo: owner/name`). Values written as `${VAR}` are read from the environment. Every option is described in [docs/configuration.md](docs/configuration.md).

### 5. Describe your KB's conventions (optional)

Add a `.meeting-agent.yml` at the root of the KB repository to tell the agent its language, which files to skip, how decision records are named and numbered, where minutes go, and which status tags the pages use. Without it, the agent uses English and generic defaults. See [docs/configuration.md](docs/configuration.md#kb-conventions-meeting-agentyml).

## Replay a meeting

```bash
uv run kb-meeting-agent replay examples/transcript.jsonl --kb my-kb
```

The agent clones (or updates) the KB, indexes it, then feeds the transcript to the agent segment by segment. Its messages are printed with an `[agent]` prefix, and decision buttons are shown with their ids.

| Option | Effect |
|---|---|
| `--config PATH` | configuration file (default `config.yml`) |
| `--kb NAME` | knowledge base to use, as named in `config.yml` (required) |
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

The agent answers when one of `agent_names` appears in a segment (`scribe` in the example configuration).

## How it behaves

- **Answers** use only KB excerpts and cite them as `path#section`; when the KB does not cover the question, the agent says so.
- **Contradictions** are posted only when the model is confident, when the quoted line really exists in the cited file, and once per subject. The agent shows the full KB line, says "the KB says…" rather than "this is wrong", and warns when the page has not been verified recently.
- **Decisions** are proposed with Validate / Edit / Ignore buttons; in a live meeting they can also be validated by voice (Edit needs a live connector: it does nothing in replay). A validated decision becomes a pull request with the record, the transcript lines it comes from (labelled as context when the exact line could not be found), and the KB pages that probably need an update (not modified). If publishing fails, the files are kept under `unpublished/`.
- **Minutes** are written at the end in two passes (summaries of 10-minute slices, then a synthesis) and published as a pull request. The full transcript is never published; decision pull requests quote only the relevant lines, with speaker and time.

## Development

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

## License

Apache-2.0
