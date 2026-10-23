---
name: audit-bugs
description: >
  Read-only audit of the Python core in src/kb_meeting_agent/ (or a target
  folder), plus connector-discord/ when asked, hunting for correctness bugs:
  meeting logic, what reaches participants / GitHub / logs (privacy, tokens,
  unverified quotes), asyncio races and lifecycle, persistence and resume,
  model-output and error handling, the connector protocol, config and KB
  conventions. Every finding is challenged adversarially and carries a repro
  path; report in the terminal and in docs/audits/, then TDD fixes on request.
  Triggers on "find bugs", "cherche les bugs", "bugs potentiels", "where can it
  break", "race condition", "audit the code for bugs". Not for: quality/debt
  (optimize), a diff (/code-review, github-pr-review), a security review of a
  diff (/security-review).
---

# Audit-bugs — hunt for latent bugs across the codebase

**Read-only** audit of the existing code for **correctness bugs** (not style
debt — that's `optimize`), then — **on request only** — TDD fixes. It is the
whole-codebase counterpart of the diff-only review skills (`/code-review`,
`github-pr-review`).

The skill **never** edits code during the audit. It produces a ranked report,
then asks the user what to fix.

**What matters most here.** The agent speaks in a live meeting and publishes to
GitHub on its own. A bug that makes it **say something false with confidence**
(a contradiction whose quote does not exist, a decision attributed to the wrong
person), **publish what must stay private** (the full transcript, an opted-out
participant's words, a token, a log message) or **lose a meeting** (minutes
never written, a crash on close, a resume that drops state) is worse than a
crash that the log shows. Weight severity accordingly.

## Step 0 — Resolve the scope

- No argument: scope = all of `src/kb_meeting_agent/`.
- With an argument (`/audit-bugs src/kb_meeting_agent/live`): that folder.
  `connector-discord/` is audited only when it is named.

Run the tooled corroboration in parallel:

```bash
uv run pytest -q                      # does the current suite pass?
uv run ruff check .                   # unused names, shadowed loop vars, B rules (mutable defaults…)
(cd connector-discord && npm test)    # only when connector-discord/ is in scope
```

There is no type checker in this project: type and `None` bugs are found by
reading. Tool output is supporting evidence, never the only source: every
finding is checked against the real code (Step 3).

## Step 1 — Audit by category (fan-out or inline depending on size)

Measure first (`wc -l` on the files in scope):

- **Scope > ~800 lines OR > 10 files** → **fan-out**: dispatch **7 subagents in
  parallel** (Agent tool, `Explore` or `general-purpose`), one per category, all
  in a single message.
- **Otherwise** → **inline**: work through the 7 categories yourself.

Each pass gets: the scope, its category, the obligation to cross-check with
`CLAUDE.md`, `README.md` § "How it behaves" and `docs/configuration.md`
(Step 2), and the output format (Step 4). An agent returns **findings only**.

**Format instruction for every agent (mandatory):** "Follow the Step 4 format
EXACTLY. For each bug give a **concrete repro path** (the sequence of calls,
segments, button clicks or connector messages that triggers it) and cite the
`file:line` you **actually opened and read**. Actively try to **refute** your
own finding before reporting it."

| # | Category | What the agent looks for |
|---|---|---|
| 1 | **Meeting logic** | `MeetingAgent` doing the wrong thing on a valid meeting: segments skipped or processed twice between extraction windows; a level (`silent`, `contradictions`, `context`) not honored; the agent answering when not addressed or ignoring an alias; a decision validated twice → two PRs, or validated after being ignored; decision numbering colliding with an open PR or an existing record; minutes missing an exchange, a decision or a participant; `snapshot()`/restore not carrying a field that changes behavior after a resume. |
| 2 | **Publication & privacy boundary** | What reaches participants, GitHub or logs that should not: a contradiction posted without `quote_exists` succeeding, or one based on a **code** chunk (code never contradicts); a KB page modified by a decision PR; transcript lines beyond the quoted ones in a PR; an opted-out participant's speech or audio kept; audio not deleted after publication; a log-only message (exception text, URL, response body) shown in the meeting instead of `PublishError.public` / `LLMConfigError.status`; a token in a URL, a remote, a log line or sent to a non-`https://github.com/` host; anything written to a code repository. |
| 3 | **Asyncio concurrency & lifecycle** | `create_task` results never awaited, cancelled or kept (lost exceptions, tasks garbage-collected); a button, command or `close()` mutating agent state while `_consume` is mid-step; `close()` re-entered or racing with incoming audio; per-speaker order broken in `TranscriptionPipeline`; a semaphore slot not released on an error path; `CancelledError` swallowed by a broad `except`; blocking I/O (git, sqlite, Whisper, file writes) on the event loop instead of `asyncio.to_thread`; a sqlite connection shared across threads. |
| 4 | **Persistence, resume & caches** | `state.json` written non-atomically or read without handling a partial/old format; a meeting resumed with stale opt-outs or gaps; retention deleting the active meeting's folder; `unpublished/` files lost on retry; the search index serving stale chunks or vectors after a file changes, is deleted or the embedding model changes; the code sync running in the background racing a search. |
| 5 | **Model output & error handling** | A model answer trusted beyond its schema: a path, slug, anchor, repo or line range from the model used without checking it exists (file writes, links, `section()`); an empty/`None` field treated as valid; `LLMUnavailable` vs `LLMInvalidOutput` vs `LLMConfigError` mis-classified (a config error that pauses forever, a transient error that stops checks for good); an exception escaping a step and killing the consumer; empty KB, empty transcript, zero participants, a meeting with no decisions. |
| 6 | **Connector protocol & Discord** | `live/protocol.py` and `connector-discord/src/protocol.js` disagreeing (header layout, endianness, message fields, `PROTOCOL_VERSION`); a message type handled on one side only; auth not using a constant-time compare or not enforced before the first frame; reconnect losing opt-outs or modals; a Discord interaction not answered or deferred in time; ids handled as JS numbers instead of strings/BigInt. |
| 7 | **Config & KB conventions** | `${VAR}` expansion edge cases; a key accepted but ignored; `.meeting-agent.yml` patterns (`filename`, `branch`, `index.row`) producing an invalid path or branch name, or a path outside the KB (`..`, absolute) from a model-provided title or slug; a status pattern or `verified_date` regex that never matches; a default that differs between `config.py`, `config.example.yml` and `docs/configuration.md`. |

## Step 2 — Context and documented choices

`CLAUDE.md`, `README.md` § "How it behaves" and `docs/configuration.md` describe
**intended** behavior: checks pause while the model is unavailable and
transcription continues; a contradiction is posted once per subject; code is
read only and never contradicts; Edit does nothing in replay; dry run is the
default and writes under `replay-out/`; the full transcript is never published.
Each agent must:

1. **Read** those docs and this file's "Known false positives" section, so as
   not to report an assumed behavior.
2. **Stay critical.** A documented behavior can still hide a bug past what the
   doc covers (a contradiction is posted once per subject, but a subject that
   differs only by case may be posted twice). When in doubt, report it as
   **PLAUSIBLE** with the exact path.

## Step 3 — Challenge before reporting

A bug that cannot be reproduced — **or that can but changes nothing** — is
noise. Refute on **two axes**, in order:

1. **Reproducibility**: look for the guard, the check, the lock, the
   validation or the test that already prevents it. If one does → REFUTED
   (cite it).
2. **Impact** (never skip): even if reproducible, **who is actually affected?**
   State nobody reads, a leak on a path that cannot be reached, a field
   restored that nothing uses → REFUTED, or at most LOW "inconsistency without
   consequence".

Then mark:

- **CONFIRMED** — exact `file:line` + concrete repro; no guard prevents it
  **and** a participant, a PR or the meeting suffers a consequence you name.
- **PLAUSIBLE** — mechanism and consequence are real but depend on something
  not verifiable here (model behavior, Discord timing, GitHub API behavior,
  scheduling under load). Name the factor.
- **REFUTED** — dropped.

Only CONFIRMED and PLAUSIBLE are reported.

## Step 4 — Synthesis and finding format

Merge the agents' outputs and **dedupe**. Each finding:

```
[HIGH] Likelihood:high Impact:high — <short title>   (Concurrency)
  File(s)   : src/kb_meeting_agent/live/session.py:760
  Repro     : <concrete sequence of segments / clicks / messages that triggers the bug>
  Impact    : <what breaks for participants, the PRs or the meeting record>
  Fix idea  : <proposed fix + the test that would prove the bug>
  Status    : CONFIRMED
```

- **Severity** `[HIGH]/[MEDIUM]/[LOW]` (same grid as `github-pr-review`) **and**
  **Likelihood × Impact** (`high/medium/low` each).
- A category 2 bug (publication & privacy) goes up one severity step even when
  unlikely: a leak cannot be taken back.

**Out-of-scope spill.** If a finding's main file is outside the scope (Step 0),
tag it **`OUT-OF-SCOPE`** and group those separately.

## Step 5 — Write the report

1. **Terminal recap**: findings sorted **by severity**, one line each.
2. **Versioned Markdown**: `docs/audits/YYYY-MM-DD-bugs.md` (create
   `docs/audits/` if needed), the full report grouped by category, with a
   progress table (`⬜ To do · 🔧 In progress — PR #N · ✅ Fixed <date> ·
   🚫 Dismissed`) so later sessions can pick up the backlog.

Then **ask** the user: "Which bugs do we fix?"

## Step 6 — Fix on request (TDD)

Nothing is applied without explicit agreement. A bug is fixed test-first:

1. **Reproduce with a failing test** that captures the correct behavior
   (`FakeProvider`, `tests/conftest.py` fixtures, `tests/live/helpers.py`
   `FakeLink`/`Clock`/`speak`, `tests/live/fake_connector.py`). Run it and watch
   it fail: a test that passes first time proves nothing.
2. **Fix** until green. For a non-trivial bug, find the root cause first.
3. **Check for regressions**: `uv run pytest -q`, `uv run ruff check .`,
   `uv run ruff format --check .`, and `(cd connector-discord && npm test)` when
   the connector or the protocol changed. Never say "fixed" without the green
   output. A fix touching the connector, the session or transcription also
   needs the `docs/manual-test.md` checklist: say so, don't claim it was run.
4. Conventional Commits, scope = package (`fix(live): …`); update the progress
   table of the audit report in the same PR.

Heavy fixes (reworking `close()`, the resume format, the protocol) **stay
proposals**: propose a plan in plan mode before touching code.

## Known false positives

_Findings the user confirmed as non-bugs. Do not report them again. (Empty at
first — grows with each audit, Step 6.)_

<!-- Format: - <file:symptom> — <why it is not a bug / where it is guarded> (confirmed YYYY-MM-DD) -->
