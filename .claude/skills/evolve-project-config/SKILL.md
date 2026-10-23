---
name: evolve-project-config
description: Use when CLAUDE.md feels stale after recent code changes, a workflow has been repeated ≥ 2 times, a new pattern emerges, or the user says "update CLAUDE.md", "mets à jour le CLAUDE.md", "create a skill for this", "capture this convention", "is the Claude config up to date?", or after a new dependency, CLI command, config key, model provider, transcription engine, protocol message or architecture refactor.
---

# Evolve Project Config

Single entry point to keep this repo's Claude config (`CLAUDE.md`,
`.claude/skills/`, `.claude/settings.json`) in step with the code. Two modes,
combinable in one session.

## Sync mode — scan the changes

In parallel:

```bash
git log --oneline -15
git diff --stat "$(git merge-base origin/main HEAD)" HEAD | tail -40
```

| Source | What to look for |
|--------|-----------------|
| `pyproject.toml` / `uv.lock` | New dependency or extra, Python version, pytest or ruff settings |
| `connector-discord/package.json` | New dependency, Node version, scripts |
| `src/kb_meeting_agent/cli.py` | New subcommand or option |
| `src/kb_meeting_agent/config.py` | New config section or key, new provider name |
| `src/kb_meeting_agent/conventions.py` | New `.meeting-agent.yml` key |
| `src/kb_meeting_agent/ports.py` | New or changed port |
| `src/kb_meeting_agent/live/protocol.py` / `connector-discord/src/protocol.js` | New message type, version bump |
| `src/kb_meeting_agent/{llm,transcription,publish}/` | New provider, engine or publisher |
| New package under `src/kb_meeting_agent/` | New layer to place in the architecture |
| `tests/` | New shared fixtures or fakes worth knowing |
| `Dockerfile` | Build or runtime change |

Gaps to detect:

| Change in the code | Possible gap in CLAUDE.md |
|------------------------|------------------------------|
| New CLI subcommand | Commands section |
| New dependency extra | `uv sync --extra …` line |
| New port or implementation | Architecture: which modules plug in behind which port |
| New model role or provider | LLM paragraph |
| Protocol change | The mirrored-protocol rule |
| New cross-cutting rule (privacy, i18n, errors) | Conventions section |
| New test helper or fake | Commands / testing note |

`README.md` and `docs/configuration.md` are user documentation; `CLAUDE.md`
links to them instead of repeating them. Check they were updated too, but they
are not this skill's output.

## Evolution mode — create rules and skills

**Rule** (a line in `CLAUDE.md`) when the constraint applies to every
conversation and breaking it produces a wrong result at once (e.g. "every
`Schema` field is required").

**Skill** (`.claude/skills/<name>/SKILL.md`) when the workflow has been run
≥ 2 times with non-trivial decisions. Candidates that would be justified here:

- Add a model provider (provider class, `factory.py`, config validation, docs,
  `tests/llm/test_providers.py`)
- Add a transcription engine (same shape under `transcription/`)
- Add a connector ↔ core message (both protocol files, both test suites,
  session handler, `docs/manual-test.md`)
- Add a `.meeting-agent.yml` convention (`conventions.py`, docs, fixture in
  `tests/conftest.py`)

Existing project skills: `audit-bugs`, `optimize`, `github-pr-review`. Keep
their file paths, commands and false-positive lists in step with the code they
describe: a renamed module or a new port is a gap in them too.

## CLAUDE.md quality criteria

| Criterion | Goal |
|---------|----------|
| **Commands** (20 pts) | `uv`, `pytest` (one test), `ruff`, `npm test`, the CLI — copy-pastable |
| **Architecture** (20 pts) | The two processes, the ports, the agent vs the session, sources, LLM roles — only what needs several files to see |
| **Non-obvious patterns** (15 pts) | Mirrored protocol, required schema fields, `en`/`fr` messages, public vs log errors |
| **Concision** (15 pts) | No generic Python or asyncio advice |
| **Freshness** (15 pts) | Python, Node, ruff rules, extras match `pyproject.toml` / `package.json` |
| **Actionability** (15 pts) | Every step runs without looking elsewhere |

## Target structure

```
# CLAUDE.md + standard header
## What this is      ← one paragraph + links to README.md and docs/
## Commands
## Architecture      ← only what is not obvious from ls
## Conventions worth knowing
```

## Ban from CLAUDE.md

- What `ls src/` shows at once
- Content of `README.md` or `docs/configuration.md` (link instead)
- Standard Python, pytest or discord.js behavior
- Secrets or real ids (`guild_id`, tokens)

## Commit

On a dedicated branch (never directly on `main`), then a PR like for code:

```bash
git switch -c chore/claude-config-<topic>
git add CLAUDE.md .claude/
git commit -m "docs(claude): <what changes>"
```
