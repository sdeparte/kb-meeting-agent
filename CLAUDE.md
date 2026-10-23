# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A meeting agent that listens to a voice meeting (through a platform connector — Discord today — or a replayed JSONL transcript) and works against a **project**: one Git-hosted Markdown knowledge base (tag `KnowledgeBase`) plus optional read-only code repositories (tag `CodeBase` + free tags like `FrontEnd`/`BackEnd`). It answers questions, flags contradictions with the KB (quoting the KB line verbatim), turns validated decisions into one PR each, and opens a minutes PR at the end. User-facing docs: `README.md`, `docs/configuration.md` (every config key, and the per-KB `.meeting-agent.yml` conventions), `docs/manual-test.md` (live Discord checklist to run before merging changes to the connector, the session or transcription).

## Commands

```bash
uv sync                                   # add --extra mlx (Apple Silicon) or --extra faster for live transcription
uv run pytest -q                          # all Python tests
uv run pytest tests/agent/test_meeting.py::test_name -q   # a single test
uv run ruff check . && uv run ruff format --check .
(cd connector-discord && npm ci && npm test)              # Node connector tests (node --test)

uv run kb-meeting-agent replay examples/transcript.jsonl --project my-project   # dry run into replay-out/
uv run kb-meeting-agent index --project my-project        # sync + index a project's repos
uv run kb-meeting-agent run                               # live meetings (needs connector + transcription config)
```

`config.yml` is git-ignored; start from `config.example.yml`. `${VAR}` values are read from the environment and unknown keys are rejected. Pytest runs with `asyncio_mode = "auto"` and `tests/` on `pythonpath` (test helpers are imported directly, e.g. `from helpers import ...`). Ruff: line length 100, rules E/F/I/UP/B.

## Architecture

Two processes in live mode:

- **A connector** (`connector-<name>/`; today `connector-discord/`, Node, discord.js): joins voice, receives per-speaker Opus, downsamples to 16 kHz mono PCM, relays slash commands/buttons/modals. It holds no meeting logic, and the core holds no platform logic: the `connector` config section gives its name, `env` (platform credentials, passed as is) and optional `command`.
- **Python core** (`src/kb_meeting_agent/`): `live/runner.py` spawns the connector as a subprocess (own process group, restarted with backoff unless it exits with `CONFIG_ERROR_EXIT`, a refused env) and talks to it over a local WebSocket (`live/link.py`, shared-secret auth). The wire format — JSON messages plus binary audio frames (`>BQB` header: kind, timestamp, user id length, then the UTF-8 user id); every id is an opaque platform string, and a user has the same id in audio, `speaking` and interactions — is defined in `live/protocol.py` and **mirrored by hand** in `connector-discord/src/protocol.js`; change both together and bump `PROTOCOL_VERSION` when incompatible.

Core layering:

- `ports.py` — the Protocols the agent depends on: `KnowledgeBase` (search/read/conventions/templates), `Publisher` (open/update PRs, `aclose`), `ChangeKeeper` (keeps a change that could not be published; `LocalKeeper` also reads it back for retry-publish, so its file layout stays in `publish/local.py`), `OutputSink` (send `OutMessage` with buttons/modals). Everything else plugs in behind these, which is why replay and tests swap implementations freely (`ConsoleSink`, `DryRunPublisher` vs `GitHubPublisher`, `LocalKeeper`, `FakeProvider`). `agent/` never imports an adapter (`publish/`, `kb/repo.py`, `live/`, a provider).
- `forges.py` — where a repository is hosted (`RepoConfig.provider`, only `github` so far): clone URL, the host the git token is scoped to, file links. `publish/factory.py` `build_publisher` picks the forge's `Publisher`. A new host is one `Forge`, one publisher and one `provider` value.
- `agent/meeting.py` — `MeetingAgent`, the transport-independent brain: feeds segments through `detection.py` (fast model: claims, decisions, topics, "is the agent addressed?", running summary), then `answering.py`, `factcheck.py`, `decisions.py`, `minutes.py` (strong model). Both `cli.py replay` and `live/session.py` drive it.
- `live/session.py` — `MeetingSession`: per-meeting state on top of the connector (join/resume, opt-out, audio buffering in `live/audio.py`, `live/pipeline.py` transcribing utterances in a bounded pool while keeping per-speaker order, final second transcription pass, closing and publishing).
- `kb/` — `project.py` `ProjectSources` implements `KnowledgeBase` over one `GitMarkdownKnowledgeBase` (`repo.py`) and N `GitCodeRepository` (`code.py`); `chunker.py` splits files, `index.py` is a hybrid lexical + embedding `SearchIndex` that re-embeds only files whose hash changed; `quote.py` verifies that a quoted KB line really exists (contradictions are dropped otherwise).
- `llm/` — `LLMProvider.complete_json(system, user, schema)` + `embed`. Every model call returns JSON validated against a pydantic `Schema` subclass (`extra="forbid"`, **all fields required, no defaults** — needed for strict structured output). Three roles from config: `fast`, `strong`, `embedding`. Errors are classified: `LLMUnavailable` (pause checks, keep transcribing), `LLMInvalidOutput`, `LLMConfigError`. `FakeProvider` (`provider: fake`) returns per-schema defaults from `FAKE_DEFAULTS` and a deterministic bag-of-words embedding.
- `conventions.py` — `KbConventions` parsed from the KB repo's `.meeting-agent.yml` (language, excludes, status tags, decision/minutes filename, index row and branch patterns). KB-specific formats belong there, not in `config.yml` or code; `templates/` holds the defaults.
- `transcription/` — `base.py` is the `Transcriber` port (synchronous, run in worker threads) and audio helpers; engines (mlx-whisper, faster-whisper, OpenAI API, fake) plug in through `factory.py`. `filtering.py` (`HallucinationFilter`) and `vocabulary.py` (the prompt hint) are post- and pre-processing, not part of the port. Engine-specific `TranscriberRole` keys are listed in `config.py` `_ENGINE_OPTIONS` and refused on other engines.

## Conventions worth knowing

- Text shown to meeting participants goes through `agent/messages.py` `t(language, key, ...)`, with entries in **both** `en` and `fr`; the language comes from the KB conventions.
- Code repositories are read-only: they feed answers to questions about the code (query rewriting sets `code`; other questions search the KB alone, and the KB leads when both are searched) and the "files probably affected" list of decision PRs, but are never used to contradict a statement and never written to.
- Exceptions carrying a `public` / `status` attribute (`PublishError`, `LLMConfigError`) separate log detail from what may be shown in the meeting; don't leak the log message to participants.
- The full transcript is never published; decision PRs quote only the relevant lines.
- Commits follow Conventional Commits with a scope matching the package (`feat(kb):`, `fix(agent):`, `feat(live):`…).
