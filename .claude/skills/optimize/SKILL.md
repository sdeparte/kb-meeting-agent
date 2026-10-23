---
name: optimize
description: >
  Read-only audit of the health of the code in src/kb_meeting_agent/ (or a
  target folder): architecture and the ports boundary, duplication, dead code,
  performance and robustness (model calls, asyncio, index, git), file
  structure, Python 3.12 idioms, configuration, over-engineering, naming,
  testability. Goal: raise a quality score out of 10 (10 weighted axes, fixed
  scale, comparable from one audit to the next) by targeting what lowers it.
  Report ranked by score gain (terminal + docs/audits/), then fixes on
  request, tracked in the report, and the score recomputed. Triggers on
  "audit the code", "find optimizations", "technical debt", "dette technique",
  "dead code", "duplication", "over-engineering", "quality score", "note de
  qualité". Not for: refactoring one file (do it directly, or /simplify on a
  diff), finding bugs (audit-bugs), reviewing a diff (/code-review,
  github-pr-review).
---

# Optimize — codebase health audit

**Read-only** audit of the existing code, then — **on request only** — safe
fixes. `/code-review` and `github-pr-review` look at *what a diff changes*;
this skill looks at *what already exists*. For **bugs**, use `audit-bugs`.

The skill **never** edits code during the audit.

## Mission: raise the quality score

The audit exists to **raise the overall quality score** by targeting what costs
it points. The scale below is fixed so scores stay comparable between audits;
change it only on purpose, and bump its version when you do.

### The grid (scale v1)

| Axis | Scored by | Weight |
|---|---|---|
| Architecture & ports | cat. 1 | **×2** — new platforms, providers and publishers plug in here |
| Duplication | cat. 2 | ×1 |
| Dead code & unused | cat. 3 (+ `ruff`) | ×1 |
| Performance & robustness | cat. 4 | ×1 |
| File structure / maintainability | cat. 5 | ×1 |
| Writing quality | cat. 6 (+ `ruff`) | ×1 |
| Configuration | cat. 7 | ×1 |
| Simplicity (over-engineering) | cat. 8 | ×1 |
| Future-proof naming | cat. 9 | ×1 |
| Tests & testability | cat. 10 | ×1 |

Sum of weights: **11**. Overall score = Σ(axis × weight) ÷ 11, rounded to 0.5.

### Scoring an axis

Start from the anchor, then adjust by at most ±0.5 with a stated reason:

| Score | Anchor |
|---|---|
| 10 | Nothing above LOW; LOWs are isolated |
| 9 | Only LOWs, at least one repeated pattern |
| 8 | One MEDIUM |
| 7 | Two or three MEDIUMs, or one MEDIUM pattern spread across the package |
| 6 | One HIGH, or four or more MEDIUMs |
| ≤ 5 | Several HIGHs; the axis blocks ordinary changes |

- **Out of score.** A real defect too small to move its axis, alone or with
  others, goes on the axis' "Out of score" line, not in the findings.
- **Estimated gain** of a finding: the axis score once it is fixed, minus the
  current one; on the overall score, × weight ÷ 11.
- **Counter-review** before writing: for each axis, check the score against
  the anchor table once more after dedupe and refutations, and that two axes
  are not paying for the same finding.

## Step 0 — Scope and reference score

- No argument: scope = all of `src/kb_meeting_agent/`.
- With an argument: that folder only. The score is then not comparable to a
  whole-package audit; the report says so.

**Reference score.** Open the latest `docs/audits/*-optimizations.md` with an
"Overall quality score" section: note its overall and axis scores, its scale
version and its open findings. Open findings are the first candidates: either
they still weigh on the score, or they were fixed and the score must show it.
No earlier audit → no reference, and the report says so. A score from another
scale version is not compared.

**Objective measures**, collected in parallel:

```bash
uv run ruff check .                                     # findings beyond the cosmetic
uv run ruff check --select C901,PLR0912,PLR0915 src     # complexity hot spots (not enforced, signal only)
find src -name '*.py' | xargs cat | wc -l               # vs the same on tests/
find src -name '*.py' | xargs wc -l | sort -n | tail    # files over ~400 lines
uv run pytest -q                                        # must be green before and after
```

Tool output is supporting evidence, never the only source (Step 3).

## Step 1 — Audit by category (fan-out or inline depending on size)

- **Scope > ~800 lines OR > 10 files** → **fan-out**: **10 subagents in
  parallel** (Agent tool, `Explore` or `general-purpose`), one per category,
  all in one message.
- **Otherwise** → **inline**: the 10 categories yourself.

Each pass gets: the scope, its category, the axis it scores, the scale above,
the axis' reference score, and the obligation to cross-check with `CLAUDE.md`,
`README.md` and `docs/configuration.md` (Step 2).

**Priority instruction for every agent:** "Find what lowers your axis' score.
Look for structural defects and repeated patterns (MEDIUM/HIGH) first,
isolated details last. Group every occurrence of a pattern into one finding."

**Format instruction for every agent:** "Your output has exactly two parts:
1. `Axis: <name> — Score: X/10 (reference: Y)`, then 2-4 lines of strengths
   checked in the code and 1-2 lines on what costs points (anchor + adjustment).
2. Findings sorted by gain, in the EXACT Step 4 format, then one 'Out of score'
   line. Cite the `file:line` you **actually opened and read**."

| # | Category | What the agent looks for |
|---|---|---|
| 1 | **Architecture & ports** | Code that bypasses the ports in `ports.py` (`KnowledgeBase`, `Publisher`, `ChangeKeeper`, `OutputSink`): `agent/` importing `live/`, `publish/`, Discord, GitHub, git or a concrete repository class; a concrete provider leaking past `llm/factory.py`, `transcription/factory.py` or `publish/factory.py`; a forge's URLs or auth outside `forges.py`; a platform's ids, names or credentials in the core instead of the connector; transport concerns (connector messages, Discord ids, modals) inside `MeetingAgent`; meeting logic inside `MeetingSession` that replay could not reach; KB-specific formats hard-coded instead of read from `KbConventions`; `live/session.py` or `agent/meeting.py` mixing responsibilities that would be one class each. |
| 2 | **Duplication** | Logic copied between `replay` (`cli.py`) and `run` (`live/runner.py`) wiring; prompt fragments or JSON-schema handling repeated across `agent/*.py` instead of `prompting.py`; the same git plumbing in `kb/repo.py` and `kb/code.py` outside `kb/git.py`; repeated error-to-message mapping; test helpers duplicated across test files. |
| 3 | **Dead code & unused** | Functions, `Schema` fields, message keys in `agent/messages.py`, config keys or `FAKE_DEFAULTS` entries never read; branches that cannot be reached; a protocol message type sent by one side and handled by none. Corroborate with `ruff` and targeted `grep`. |
| 4 | **Performance & robustness** | Model calls that could be batched or skipped (the `fast` role runs every ~30 s: anything wasted there costs latency for the whole meeting); embeddings recomputed for unchanged content; repeated full-file reads or index loads; blocking work on the event loop; unbounded growth over a long meeting (transcript kept in prompts, sets of flagged subjects, task lists); missing timeouts on HTTP, git or subprocess calls. |
| 5 | **File structure / maintainability** | Modules over ~400 lines carrying several concerns (`live/session.py`, `agent/meeting.py`); a helper living in the wrong package; dataclasses / pydantic models defined far from their only user, or one used by three packages buried in one of them. |
| 6 | **Writing quality** | Python 3.12 idioms (`match`, `X \| None`, dataclasses with `frozen`/`slots` where the codebase uses them, `pathlib`), naming, comment density consistent with the neighbors, `from __future__ import annotations` present like the other modules. Corroborate with `ruff`. |
| 7 | **Configuration** | Magic numbers and tunables (intervals, timeouts, thresholds, chunk sizes, `k`, retry delays, char limits) scattered in code that a user would want to change: propose a named module constant or a `config.yml` key (documented in `docs/configuration.md`). Do not flag what is already a named constant or a config key. |
| 8 | **Simplicity (over-engineering)** | Two sub-cases, always say which: **(a)** an abstraction with no real second user (a Protocol with one implementation **and** no fake/test double **and** no planned second one — the ports, `LLMProvider` and `Transcriber` have several and are legitimate); **(b)** a method more complex than its job (nesting an early return would flatten, validation of what pydantic or the type already guarantees, over-splitting that forces jumping between files). (a) is fixed by inlining; (b) by simplifying the body without changing the contract. |
| 9 | **Future-proof naming** | A name already in place that describes *what happens today* rather than the property a documented future need will branch on — only when that need is on record (README "Status": other meeting platforms; a second implementation already present in the same Protocol or enum). No anchor → no finding. |
| 10 | **Tests & testability** | What prevents testing `src/` simply: time, randomness, subprocesses, network or filesystem called directly with no injection point (compare with `SessionDeps.clock_ms`); logic only reachable through a full live session; tests coupled to private attributes or exact prompt wording; fixtures duplicated across files; a module of `src/` with no test. The test-line ratio measures volume, not quality. |

## Step 2 — Guard rail: documented choices

`CLAUDE.md`, `README.md` and `docs/configuration.md` record **intentional**
choices (ports with fakes for replay and tests, three model roles, pydantic
schemas with every field required, protocol mirrored by hand in Python and JS,
dry run by default, messages in `en` and `fr`). Each agent must:

1. **Not report an assumed choice**, nor anything in "Confirmed exceptions"
   below.
2. **Stay critical of it.** A documented rule that looks wrong itself
   (obsolete, contradictory, a source of debt) is reported as a
   **`[CONVENTION]`** finding, separate from code findings.

## Step 3 — Verify before reporting

Each candidate is checked against the **real file** and marked **CONFIRMED**,
**PLAUSIBLE** (name what could not be verified) or **REFUTED** (dropped). Each
finding states a concrete observation ("`_replay` and `run` both build the
publisher from `--publish` at cli.py:96 and runner.py:120"), never "looks
odd". A category 9 confusion with no future need on record is REFUTED, not a
precautionary LOW.

## Step 4 — Synthesis, format, scores

Merge and **dedupe** (one finding, gain counted on its main axis only):

```
[MEDIUM] Impact:high Effort:low — <short title>   (Duplication)
  File(s)   : src/kb_meeting_agent/cli.py:96, src/kb_meeting_agent/live/runner.py:120
  Problem   : <observation + proof>
  Fix idea  : <concrete refactor>
  Gain      : Duplication +0.5 (→ overall +0.05)
  Status    : CONFIRMED
```

Severity `[HIGH]/[MEDIUM]/[LOW]` (same grid as `github-pr-review`) **and**
Impact × Effort (`high/medium/low`). Then set the ten axis scores, compute the
overall score, run the counter-review. A finding whose main file is outside the
scope is tagged **`OUT-OF-SCOPE`** and grouped separately.

## Step 5 — Write the report

1. **Terminal recap**: the improvement plan (batches by gain ÷ effort, with the
   target score after each), then the findings one line each.
2. **Versioned Markdown** `docs/audits/YYYY-MM-DD-optimizations.md`, sections in
   order:
   1. **Overall quality score** — rounded score, scale version, objective
      measures, table of the 10 axes (score, reference, strengths, what costs
      points).
   2. **Improvement plan** — batches and target score after each.
   3. **Progress** — one row per finding: `⬜ To do · 🔧 In progress — PR #N ·
      ✅ Fixed <date> · ⏭ Postponed · 🚫 Dismissed (checked <date>) · ➖ Obsolete`.
   4. **Detail by category** — full findings, then the "Out of score" line.
   5. **`[CONVENTION]` findings**.

`github-pr-review` reads this report to know which zones are fragile.

Then **ask**: "What do we fix?", proposing the first batch of the plan.

## Step 6 — `[CONVENTION]` findings

Ask the user to decide each one: **"legitimate choice"** → add it to "Confirmed
exceptions" below; **"real problem"** → fix the rule at its source (`CLAUDE.md`
or the doc that states it) in the same PR as the code.

## Step 7 — Fix on request

Nothing without explicit agreement, in the order of the improvement plan.

- **Safe fixes** (dead code, simple duplication, named constants, idioms) →
  apply, then `uv run pytest -q`, `uv run ruff check .`,
  `uv run ruff format --check .`, and `(cd connector-discord && npm test)` if
  the connector changed. Never claim "fixed" without the green output.
- **Architecture refactors** (splitting `MeetingSession`, moving a
  responsibility across packages, changing a port) → **stay proposals**: plan
  in plan mode first.
- Conventional Commits with the package scope (`refactor(live): …`).
- **Track each finding in the audit report**, in the same PR as the fix: its
  progress row, plus `Fix:` / `Remaining:` / `Checked:` lines under the
  finding, and a follow-up section with the recomputed score once the suite is
  green.

## Confirmed exceptions

_`[CONVENTION]` findings the user confirmed as legitimate choices. Do not
report them again. (Empty at first — grows with each audit, Step 6.)_

<!-- Format: - <file:rule> — <why it is legitimate> (confirmed YYYY-MM-DD) -->
