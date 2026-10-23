# github-pr-review — angle checklists

Full checklist of each of the 10 angles of Step 3, and what a finding of each
kind must contain. Every subagent dispatched in Step 3 reads this file for its
own angle(s); in inline mode, read it once before sweeping.

1. **Line-by-line correctness** — inverted conditions, off-by-ones (segment
   windows, line ranges, 1-based vs 0-based lines), swallowed exceptions,
   wrong-variable copy-paste, unguarded `None`, a coroutine called without
   `await` — read the *enclosing* function too, not just the changed lines.
2. **Removed-behavior audit** — for every deleted or replaced line, name the
   invariant it enforced and check the replacement re-establishes it (a dropped
   `quote_exists` check, a flagged-subject dedupe no longer applied, an
   `asyncio.to_thread` turned into a blocking call, a token-scoping condition
   removed, a `t(...)` key removed from one language only).
3. **Cross-file tracer** (cross-cutting) — for each new or changed symbol, grep
   its callers and check the change holds at every call site: a new parameter
   not passed by `cli.py` (replay) **and** `live/` (run); a widened or narrowed
   port in `ports.py` not matched by every implementation (`ProjectSources`,
   `GitHubPublisher`, `DryRunPublisher`, `LocalKeeper`, `ConnectorSink`,
   `ConsoleSink`, test doubles); a `Schema` field renamed but still read, or missing from
   `FAKE_DEFAULTS`; a config key added to `config.py` but not to
   `docs/configuration.md` / `config.example.yml`; a protocol message changed
   in `live/protocol.py` but not in `connector-discord/src/protocol.js` (or the
   reverse); a field added to the agent state but not to `snapshot()` /
   restore.
4. **Publication & privacy boundary** (cross-cutting, project-specific) — the
   agent speaks in meetings and publishes to GitHub unattended. Follow every
   new or changed path from input to output and flag: a statement shown as a
   contradiction without its quote verified in the cited file, or based on a
   code chunk (code never contradicts); a KB page or a code repository
   written to; transcript text beyond the quoted lines reaching a PR, or an
   opted-out participant's words or audio kept; exception text, URLs or
   response bodies shown to participants instead of the public summary
   (`PublishError.public`, `LLMConfigError.status`); a token reaching a URL, a
   git remote, a log line or a host other than `https://github.com/`; a
   model-provided slug, title or path used in a file path or branch without
   sanitizing (`..`, absolute paths). This stays cross-cutting because the
   input and its check often sit in different files (a model answer parsed in
   `agent/`, written by `publish/`).
5. **Reuse / simplification / efficiency** — does the new code reimplement
   something already there (`prompting.py`, `kb/git.py`, `kb/quote.py`,
   `slugify`, `t()`, the test helpers)? Extra model calls on the `fast` path
   (every ~30 s of meeting), embeddings recomputed for unchanged text, a file
   or index read in a loop?
6. **Conventions** — check the diff against `CLAUDE.md` and quote the exact
   rule and the exact line that breaks it. Common ones:
   - `Schema` subclasses: every field required, no defaults (strict structured
     output); a new schema has its entry in `FAKE_DEFAULTS`.
   - Text shown to participants goes through `t(language, key)` with **both**
     `en` and `fr` entries.
   - The agent depends on the ports, not on concrete classes.
   - `from __future__ import annotations`, ruff clean (`E, F, I, UP, B`),
     line length 100.
   - Tests use the fakes (`FakeProvider`, `FakeLink`, `Clock`), not the
     network; `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed).
   - Docs updated with user-facing changes: `README.md`,
     `docs/configuration.md`, `docs/manual-test.md` when the live flow changes.
7. **Overengineered for the current need** — first state, in one sentence, the
   **concept** this PR delivers (the problem it solves, not how). Then ask: is
   there a materially simpler implementation of *that concept* with what the
   codebase or the standard library already provides? Look for a new Protocol
   for a single implementation with no fake, a new background task where a
   direct `await` suffices, a cache with no measured cost behind it, a new
   module for a few lines that belong to an existing one, more moving parts
   than the data flow needs. Sketch the alternative and check it delivers the
   concept and its real edge cases; when it changes an incidental behavior the
   PR's tests assert, name the difference. **Out of scope:** code that
   anticipates a plausible future need is a legitimate call — never flag it for
   that reason.
8. **Legitimacy of the carrying module** — does the new logic live where
   `CLAUDE.md`'s architecture puts it? Meeting logic in `agent/` (reachable
   from replay), transport in `live/` and `connector-discord/`, repository
   access in `kb/`, GitHub in `publish/`, providers behind `llm/factory.py` and
   `transcription/factory.py`, KB formats in `.meeting-agent.yml` /
   `conventions.py`. Also the reverse: a class (`MeetingSession`,
   `MeetingAgent`) quietly growing another responsibility instead of a new
   module, or a new module for what is a method on an existing class. Name
   where the code should live.
9. **Sibling-pattern** (cross-cutting) — for every "fix pattern applied" noted
   in Step 2, grep the diff (and `src/` when warranted) for other occurrences of
   the same shape **not** touched by this PR: the same unverified model output
   in a sibling step, the same missing `to_thread` in the other repository
   class, the same message key missing in `fr`. Name the original fixed
   location (thread id or fixup commit) and the exact unfixed twin.
10. **Naming & vocabulary clarity for future implementers** (cross-cutting) —
    for every new or repurposed name in shared vocabulary (a port method, a
    `Schema` field, a protocol message type, a config key, a tag, an
    intervention level), ask: could the next feature's author read it and pick
    the wrong case? Generative check: the code can be correct today and still
    set a trap. Only flag it against a concrete future case — another meeting
    platform (README "Status"), a second implementation already present in the
    same Protocol, a config value already documented but not yet used.

Every candidate needs a concrete failure scenario (inputs/state → wrong
output), not "this looks off". An **overengineered** finding states the
concept, sketches the simpler alternative, confirms it covers the real edge
cases and lists the incidental behavior it changes. A **legitimacy** finding
names the module that should carry the code. A **sibling-pattern** finding
names the fixed original and the unfixed twin. A **naming** finding names the
concrete future case it would mislead.
