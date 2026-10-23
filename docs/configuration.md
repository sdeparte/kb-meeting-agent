# Configuration

Two files configure the agent:

- **`config.yml`**, on the machine that runs the agent: models, projects and their repositories, secrets, default behaviour.
- **`.meeting-agent.yml`**, at the root of each KB repository: that KB's conventions. It travels with the KB, so every instance that uses the KB writes in the same format.

## Instance configuration (`config.yml`)

Values written as `${VAR}` are replaced by the environment variable `VAR`; the agent refuses to start if it is not set. Unknown keys are rejected.

```yaml
agent:
  name: Scribe
  aliases: []
data_dir: ~/.local/share/kb-meeting-agent

llm:
  fast:      { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "qwen3:14b", request_options: { reasoning_effort: "none", temperature: 0, max_tokens: 8192 } }
  strong:    { provider: anthropic, model: claude-opus-5-5, api_key: "${ANTHROPIC_API_KEY}", effort: high }
  embedding: { provider: openai-compatible, base_url: "http://localhost:11434/v1", model: "bge-m3" }

projects:
  my-project:
    repos:
      kb:
        repo: owner/my-kb
        tags: [KnowledgeBase]
        token: "${GITHUB_TOKEN}"
      back:
        repo: owner/my-backend
        tags: [CodeBase, BackEnd]
        token: "${GITHUB_CODE_TOKEN}"

defaults:
  intervention_level: contradictions
```

### Top level

| Key | Default | Meaning |
|---|---|---|
| `agent.name` | `agent` | the agent's name. A segment containing it (whole word, ignoring case and accents) is a request to the agent. The agent introduces itself with it in the recording notice, the minutes name it "<name> (AI)" ("(IA)" in French), and it is given to Whisper as a vocabulary hint. Prefer a word nobody says by accident. |
| `agent.aliases` | `[]` | other words that address the agent, e.g. a variant spelling or how Whisper tends to transcribe the name. They are only used to recognise that the agent is addressed: unlike `agent.name`, they are not hinted to Whisper, which would learn the misspellings |
| `data_dir` | `~/.local/share/kb-meeting-agent` | where clones and search indexes are kept (`projects/<project>/<repo>/repo`, `projects/<project>/<repo>/index.sqlite`) |

### `llm.fast`, `llm.strong`, `llm.embedding`

| Key | Meaning |
|---|---|
| `provider` | `anthropic`, `openai-compatible`, or `fake` (canned answers, for tests and dry runs) |
| `model` | model name as the provider knows it |
| `base_url` | `openai-compatible` only: the server's `/v1` URL |
| `api_key` | API key; optional for local servers |
| `effort` | `anthropic` only: `low`, `medium`, `high`, `xhigh` or `max` |
| `request_options` | `openai-compatible` only: extra fields added to every request, as is. With Ollama, `{ reasoning_effort: "none" }` switches off the reasoning of models such as Qwen3, which otherwise thinks before every answer (about 20 s instead of under 1 s on a 16 GB Mac mini). Set `temperature: 0`: servers otherwise sample (0.8 with Ollama), and the same question gets different answers (on qwen3:8b, "every mini-game in production" gave 11, then 3, then 2). Keep reasoning off with it on Qwen3, whose authors advise against temperature 0 while it reasons. OpenAI's reasoning models (o series, GPT-5) refuse temperature 0: leave it out there. Set `max_tokens` (e.g. `8192`) so that a model repeating itself fails instead of running on: Ollama's context shift never stops it; on vLLM, keep the prompt plus `max_tokens` within the model's context, or it rejects the request |
| `refusal_fallback` | `anthropic` only: when the model declines a request, let the API retry it on a fallback model (default `false`) |

`embedding` must be `openai-compatible` (or `fake`): Anthropic has no embeddings endpoint, and the configuration is rejected otherwise. Changing the embedding model rebuilds the index on the next run.

### `projects.<project>.repos.<name>`

A project groups the repositories a meeting uses; `/meeting start project:<project>` and `--project <project>` name it. Each repository carries tags:

- **`KnowledgeBase`**: the Markdown KB. Exactly one per project. Its conventions, glossary and templates apply; it is the only source for fact-checks and "related page" messages, and the only repository that receives pull requests.
- **`CodeBase`**: a code repository, read only. Its files are used to answer questions about the code ("which code handles…?", "how is … implemented?"), and listed in decision pull requests when a decision probably requires changing them. Other questions are answered from the knowledge base alone, and statements are never checked against code. When code is searched, the knowledge base still leads the excerpts.
- **Free tags** (letters, digits, `-`, `_`), such as `FrontEnd` or `BackEnd`: they label code citations (`[BackEnd] back:src/x.php:12-70`) and steer the search. When a question about the code points at one (say, "how does the back compute it?"), its repositories rank higher; the others are still searched.

A repository is `KnowledgeBase` or `CodeBase`, never both. The configuration is rejected otherwise.

| Key | Default | Meaning |
|---|---|---|
| `provider` | `github` | where the repository is hosted. Only `github` for now; a host is added in `forges.py` (clone URL, git auth, file links) plus a publisher in `publish/` |
| `repo` | (required) | repository on that host, `owner/name` |
| `tags` | (required) | see above |
| `base_branch` | `main` | branch the agent reads (and, for the KB, opens pull requests against) |
| `token` | none | GitHub token. KB: required for `--publish` and for a private KB, with Contents and Pull requests read and write. Code repository: Contents read only, for a private repository. |
| `clone_url` | `https://github.com/<repo>.git` | clone from another URL or a local path instead. The token is only sent to the host of `provider` (`https://github.com/`). |
| `language` | `en` | `KnowledgeBase` only: language of the agent's messages, pull requests and generated documents when the KB's `.meeting-agent.yml` does not set `language` (the KB's own setting wins) |
| `include` | all files | `CodeBase` only: glob patterns; when set, only matching files are indexed (`src/**`) |
| `exclude` | none | `CodeBase` only: glob patterns of files not to index, on top of the defaults below |

**Which code files are indexed.** The files tracked by Git, minus:

- lockfiles (`*.lock`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`), dependencies and builds (`vendor/`, `node_modules/`, `build/`, `dist/`, `.dart_tool/`), generated code (`*.g.dart`, `*.freezed.dart`, `*.min.js`, `*.map`);
- secrets files, whatever their case: `.env*`, `*.env`, `*.pem`, `*.key`, SSH keys (`id_rsa*`, `id_dsa*`, `id_ecdsa*`, `id_ed25519*`), keystores (`*.keystore`, `*.jks`, `*.p12`, `*.pfx`, `key.properties`), package and network credentials (`.npmrc`, `.netrc`, `.pypirc`), Terraform variables and state (`*.tfvars`, `*.tfstate*`), Firebase configs (`google-services.json`, `GoogleService-Info.plist`), and any name containing `secret` or `credential`;
- files holding a secret, whatever their name: a private key, a GitHub, AWS, OpenAI-style, Slack, Stripe, Google or GitLab token, or a password written in a URL (`postgres://app:pw@db`, not `${PASSWORD}`). A warning names each file skipped this way;
- symbolic links, binary files and files over 200 KB.

An indexed excerpt can be quoted in the meeting channel: never rely on these rules alone to keep a secret out of a repository.

Patterns match the whole path or the file name; `*` also matches `/`. Files are cut in windows of about 60 lines, ending on a blank line when one is near, with 10 lines of overlap.

**Indexing.** The KB is synced before the agent joins. Code repositories are synced in the background once the meeting has started: searches use what is already indexed, and the agent says so once when a repository has never been indexed or cannot be reached. The first indexing of a large repository takes a while: run `kb-meeting-agent index --project <project>` beforehand. Later syncs only re-index changed files; changing `include` or `exclude` adds or removes files without re-reading the others; changing the embedding model, or a new version that detects more secrets, rebuilds the index.

**What leaves a code repository.** Code excerpts are quoted in the meeting channel and sent to the models. Answers that cite code go into the minutes model's input, and a decision pull request lists the code files it probably affects, linked; the drafting model is told never to copy code into the decision itself. Both pull requests are opened on the knowledge base: keep it no more visible than the code repositories.

### `defaults`

| Key | Default | Meaning |
|---|---|---|
| `intervention_level` | `contradictions` | `silent`: speaks only when addressed. `contradictions`: also flags statements that contradict the KB. `context`: also links related KB pages. |
| `contradiction_min_confidence` | `0.8` | minimum model confidence (0 to 1) to post a contradiction |
| `context_min_interval_minutes` | `5` | minimum delay between two "related page" messages |
| `stale_page_days` | `60` | a contradiction quoting a page verified longer ago than this mentions the page's age |
| `auto_leave_empty_minutes` | `5` | the agent leaves when no human has been in the voice channel for this long |
| `transcription_lag_alert_seconds` | `30` | post a message when the transcription falls this far behind |
| `transcript_retention_days` | `30` | meeting folders (audio, transcripts, state, kept files) are deleted once they have not been updated for this long, including meetings abandoned after a crash |

## Discord and transcription

Needed only by `kb-meeting-agent run`.

### `discord`

| Key | Default | Meaning |
|---|---|---|
| `token` | (required) | bot token |
| `guild_id` | (required) | server the agent serves; slash commands are registered there |
| `node` | `node` | Node.js 22.12+ executable |
| `connector_dir` | `connector-discord/` of this checkout | where the connector lives |

The connector only receives the Discord token, the guild id and the local connection details, never model keys or the GitHub token.

### `transcription`

| Key | Default | Meaning |
|---|---|---|
| `language` | auto-detected | language passed to Whisper (`fr`, `en`…) |
| `workers` | `2` | utterances transcribed at the same time |
| `live` | (required) | engine used during the meeting |
| `final` | none | engine for the second pass at the end; the minutes are written from it |
| `hallucination_phrases` | `[]` | phrases removed from transcriptions, on top of the built-in list ("Sous-titres réalisés par la communauté d'Amara.org", "Thanks for watching"…); an utterance that is only "Merci." or "Thank you." is also dropped |
| `min_utterance_seconds` | `0.4` | shorter utterances are dropped |
| `max_no_speech_prob` | `0.6` | utterances the engine marks as probably not speech are dropped (mlx-whisper always reports 0, so it never fires there) |
| `max_compression_ratio` | `2.4` | transcriptions that compress better than this are dropped: Whisper stuck in a loop ("Eik, Disa, Eik, Disa, …"). Speech, even repeating a phrase three times, stays under 2; `null` disables. Whisper uses the same threshold |
| `min_voiced_seconds` | `0.2` | utterances with less audio above -40 dBFS are not transcribed: Whisper turns near-silence into "Merci." |
| `min_avg_logprob` | `-1.0` | transcriptions the engine is less confident about are dropped (`null` disables; the openai-compatible engine does not report it) |
| `vocabulary` | `[]` | terms hinted to Whisper before the glossary, e.g. `["la KB"]` so that "la KB" is not heard as "l'AKB". Give a term with the words around it when they sound alike: "la KB" and "l'AKB" are the same sounds, and `[KB]` alone still gave "l'AKB" |
| `vocabulary_max_chars` | `600` | length of the vocabulary hint: the agent's `agent.name` (not its aliases), then `vocabulary`, then the terms of the KB glossary's tables (first cells, then `code` spans), leaving out status tags, commit hashes and, among the `code` spans, code identifiers |

Engine keys (`live`, `final`):

| Key | Meaning |
|---|---|
| `provider` | `mlx-whisper` (macOS, Apple GPU, `--extra mlx`), `faster-whisper` (CPU or CUDA, `--extra faster`), `openai-compatible` (`/v1/audio/transcriptions`) or `fake` |
| `model` | model name or Hugging Face repository |
| `base_url`, `api_key` | `openai-compatible` only |
| `device`, `compute_type`, `beam_size` | `faster-whisper` only (`auto`, `int8`, `1`) |
| `temperature_fallback` | `mlx-whisper` and `faster-whisper` only, refused elsewhere (default `true`): when the text loops or the model is unsure, decode the utterance again at higher temperatures, up to 6 times. Set `false` on `live`: these retries are mostly on noise that is dropped anyway, and they hold up the utterances behind them (on recorded meetings: half of the GPU time, up to 8 s for one utterance, for 2 utterances in 100 rescued). Keep it on `final`, which has the time |

Without a GitHub `token` for the KB, `run` writes what it would publish under `<data_dir>/dry-run/`, and the channel shows these pull requests as `dry run: <branch>` (local paths are never posted).

## KB conventions (`.meeting-agent.yml`)

Every key is optional. Example for a French KB with numbered decision records and an index table:

```yaml
language: fr
instructions: [CONTRIBUTING.md]
exclude: [mockups/**, minutes/**]
authoritative: [reference/configuration.md]
glossary: reference/glossary.md

page_header:
  verified_date: '^> \*\*Vérifié le\*\* (\d{4}-\d{2}-\d{2})'

statuses:
  - {pattern: '[PROD]', meaning: in_production}
  - {pattern: '[EN COURS]', meaning: in_progress}
  - {pattern: '[PRÉVU]', meaning: planned}
  - {pattern: '[ÉCARTÉ]', meaning: rejected}

decisions:
  dir: decisions
  filename: '{number:04d}-{slug}.md'
  template: .meeting-agent/decision.md
  default_status: acceptée
  scopes: [client, serveur, les deux, KB]
  index:
    file: decisions/README.md
    row: '| [{number:04d}]({filename}) | {title} | {status} |'
  branch: 'decision/{date}-{slug}'

minutes:
  dir: minutes
  filename: '{date}-{slug}.md'
  template: .meeting-agent/minutes.md
  index:
    file: minutes/README.md
    row: '| {date} | [{title}]({filename}) | {participants} |'
  branch: 'minutes/{date}-{slug}'
```

### General

| Key | Default | Meaning |
|---|---|---|
| `language` | `en` | language of the agent's messages, pull requests and generated documents (`en` and `fr` messages are built in; other languages fall back to English messages, but generated documents follow `language`) |
| `instructions` | `[]` | files given to the model when it writes decision records and minutes, for example a contribution guide. Truncated to 12,000 characters in total. |
| `exclude` | `[]` | glob patterns of Markdown files not to index (`*` also matches `/`) |
| `authoritative` | `[]` | files ranked higher in search, for example the page that holds reference values |
| `glossary` | none | given to the model when it rewrites a question into search queries, to map names to identifiers (first 4,000 characters) |
| `page_header.verified_date` | none | regular expression with one capture group matching a page's last verification date (`YYYY-MM-DD`). The matching line is not indexed. |
| `statuses` | `[]` | status tags used in pages. `meaning` is one of `in_production`, `in_progress`, `planned`, `rejected`: a value under a planned item is not treated as the production value, and restating a rejected idea is flagged as already rejected. |

### `decisions`

| Key | Default | Meaning |
|---|---|---|
| `dir` | `decisions` | folder of decision records |
| `filename` | `{number:04d}-{slug}.md` | file name. With `{number}`, the agent takes the next free number, counting the KB as synced at the start of the meeting, files added by open pull requests and numbers already used in the meeting. A record merged during the meeting is not counted. |
| `template` | built-in English template | file in the KB used as the record template |
| `default_status` | `accepted` | value of `{status}` |
| `scopes` | `[]` (any) | allowed values of `{scope}`, written as is: use the KB's language. Two values may not differ only by case, accents or spacing. The model is told the list; a case, accent or spacing variant is written with the listed spelling, any other answer is asked again once, then the record is not published and the channel is told (the decision stays pending). Empty: the model picks a scope in the KB's vocabulary. |
| `index.file`, `index.row` | none | file the agent adds a row to, after the last table row of the file (code blocks ignored): keep the index as the file's last table. Nothing is added if the file does not exist or has no table yet (a warning is logged): start the index with its header row. In the row, `|` is escaped and line breaks become spaces. |
| `branch` | `decision/{date}-{slug}` | branch name; on GitHub, `-2` to `-9` is appended if it already exists. Dry runs and `unpublished/` reuse the name. |

### `minutes`

| Key | Default | Meaning |
|---|---|---|
| `dir` | `meetings` | folder of minutes |
| `filename` | `{date}-{slug}.md` | file name |
| `template` | built-in English template | file in the KB used as the minutes template. The agent writes the sections of `{body}` itself, with headings in the KB's language: `instructions` shape their content and style, not their structure. |
| `index.file`, `index.row` | none | as for decisions: file the agent adds a row to in the minutes pull request, after the last table row of the file (code blocks ignored). Nothing is added if the file does not exist or has no table. |
| `branch` | `meetings/{date}-{slug}` | branch name |

### Template placeholders

Templates are Markdown files. `{key}` and `{key:format}` (Python format, for example `{number:04d}`) are replaced for the keys below; any other brace is left as is.

| Template | Keys |
|---|---|
| decision record, decision `filename` and `branch` | `number` (numbered KBs only), `title`, `slug`, `status`, `date`, `scope`, `context`, `decision`, `consequences`, `sources` |
| decision `index.row` | the same, plus `filename` and `path` |
| minutes, minutes `filename` and `branch` | `title`, `slug`, `date`, `participants`, `body` |
| minutes `index.row` | `title`, `slug`, `date`, `participants`, `filename`, `path` |

`date` is the meeting date (`YYYY-MM-DD`); `slug` is ASCII kebab-case. Keep model-written fields such as `title` out of `filename` and `branch`: use `slug`.
