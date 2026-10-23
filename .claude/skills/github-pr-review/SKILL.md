---
name: github-pr-review
description: >
  Review a GitHub pull request on this repo and post the findings as inline
  review comments directly on GitHub, each prefixed with a severity tag
  ([HIGH]/[MEDIUM]/[LOW]) and a concrete fix suggestion. Triggers whenever the
  user gives a github.com PR URL (or "PR #N", "la PR #N") and asks to review
  it, "add comments", "ajoute des commentaires", "revue la PR et commente", or
  otherwise wants findings posted to the PR rather than printed in the
  terminal. Distinct from `/code-review`, which reviews the local diff and does
  not touch GitHub. Keywords: review PR, PR comments, inline comments, GitHub
  review, commenter la PR, severity.
allowed-tools:
  - Bash(gh:*)
---

# GitHub PR Review (inline comments)

Reviews a PR's diff and posts findings as **inline GitHub review comments**,
each leading with a severity tag so the author can triage without opening every
thread. `/code-review` analyzes and reports in chat; this skill also publishes
to GitHub, in English (like the repo's commits, PRs and docs), and applies this
project's own conventions and false-positive traps.

If the user only wants the analysis and hasn't asked for comments to be posted,
use `/code-review` instead — posting is visible and hard to undo (Step 6).

**One pass on a large, actively-iterated PR is a sample, not full coverage.**
Three things measurably close the gap and are mandatory: Step 2 (read what
prior reviews already settled, so this pass doesn't re-litigate it), angle 9
(propagate a fix pattern to its siblings), and the per-file-cluster fan-out of
Step 3 (every localized angle accounts for every hunk in its scope). Repeat
findings across rounds are expected; the failures worth fixing are re-flagging
something already decided, missing the sibling of a fixed bug, and an agent
silently skipping hunks.

**A hunk-coverage number measures reading, not correctness.** Report it as "X/Y
hunks examined for this angle", never as a confidence score.

## Step 1 — Resolve the PR and fetch the diff

```bash
gh pr view <url-or-number> --json number,headRefOid,headRefName,baseRefName,title,body,additions,deletions,changedFiles
gh pr diff <url-or-number> > "$SCRATCHPAD/pr_diff.diff"
wc -l "$SCRATCHPAD/pr_diff.diff"   # sanity-check it isn't suspiciously short
```

Write to the session scratchpad directory (see the environment prompt), not
`/tmp`.

If the PR's `headRefName` is the current branch (`git branch --show-current`),
`Read`/`Grep` the working tree for full context around each hunk — cheaper than
reconstructing it from the diff, and lets you check claims against real code.
Otherwise `gh pr checkout <number>` in a worktree when the review needs it.

The PR may be stacked on another PR (`baseRefName` is not `main`): review only
its own diff, and treat the base PR's code as existing code.

## Step 2 — Read prior review history first

Skip only if this returns nothing (first review):

```bash
gh api repos/<owner>/<repo>/pulls/<number>/comments --paginate \
  --jq '.[] | "=== id:\(.id) review:\(.pull_request_review_id) path:\(.path) line:\(.line) ===\n\(.body)\n"'
```

Sort every thread into:

- **Fixed and confirmed** — a reply says it was addressed (a fixup commit,
  "Fixed…", "Corrigé…"). Spot-check the highest-severity ones against the
  current file; don't re-derive every one.
- **Explicitly declined** — the author saw it and decided against ("by design",
  "choix assumé", "won't fix"). **Do not re-flag it**, unless the surrounding
  code changed the tradeoff (a new caller, a new edge case). If unsure, say so in
  the finding rather than silently re-posting.
- **Still open** — no reply, or one that doesn't resolve it. Restate it if still
  reproducible.
- **Fix patterns applied** — for every fixed thread, one line on the *shape* of
  the fix (e.g. "checked a model-provided path with `exists()` before reading
  it"). This seeds angle 9.

### Step 2b — Read the docs the diff touches

- `CLAUDE.md` (architecture and conventions), `README.md` § "How it behaves",
  `docs/configuration.md`. A diff that changes a behavior these documents
  describe **without updating them** (and without the PR body saying so) is a
  **doc drift** finding, `[MEDIUM]` by default, `[LOW]` for wording only.
- A change to the connector, the session or transcription: check the PR says
  `docs/manual-test.md` was run, or note in the summary that it should be.
- Doc paths the diff adds (in `CLAUDE.md`, `docs/`, comments) must exist on the
  PR branch; each dead one is a `[LOW]` finding on its line.
- **Quality regression.** Open the latest `docs/audits/*-optimizations.md` with
  an "Overall quality score" section, if any. A diff that adds one more
  occurrence of a pattern an open finding already lists is a finding: `[MEDIUM]`
  when it drops an axis a step on the touched files, `[LOW]` when it only widens
  the pattern. Cite the audit finding's number. Hand this to the angle 5, 6 and
  9 agents.

## Step 3 — Find candidates across multiple angles

Ten angles in two groups: **localized** angles look at a hunk in isolation and
are sharded by file so each agent sweeps a small slice *exhaustively*;
**cross-cutting** angles need the whole picture and stay whole-diff.

**Fan-out or inline by size** (`wc -l` on the diff):

- **Diff ≤ ~800 lines AND ≤ 10 files** → **inline**: all 10 angles yourself.
  Before Step 4, write a one-line verdict per angle (finding / nothing / not
  applicable) — nothing else stops an angle being silently skipped.
- **Otherwise** → **fan-out**, in two parts:

  **A. Cross-cutting angles (3, 4, 9, 10) — one agent each, whole diff**, with
  the path to angles.md, its angle number, the Step 4 output contract, and for
  angle 9 the fix-patterns list from Step 2.

  **B. Localized angles (1, 2, 5, 6, 7, 8) — sharded by file cluster.**
  Partition the changed files, in diff order, into clusters of ~700-800 diff
  lines (`grep '^diff --git'` for boundaries, `grep -c '^[+-]'` per section for
  size). Keep a source file and its test (`src/kb_meeting_agent/live/session.py`
  and `tests/live/test_session.py`) in the same cluster. Three roles per
  cluster:
  - Role A — angles 1 + 2 (does it do what it should; does it keep what the
    replaced code guaranteed)
  - Role B — angles 5 + 7 (redundant vs. overbuilt). Give them the PR title and
    body: angle 7 judges against the PR's concept.
  - Role C — angles 6 + 8 (fits the rules; lives where expected)

  One subagent per (role, cluster) pair (Agent tool, `general-purpose`), all in
  one message. Each gets its cluster's hunks (not the whole diff), its angle
  numbers and the path to angles.md, "read the full function/class around each
  hunk", the Step 4 output contract, and the obligation to return a **coverage
  manifest**: for every hunk, a finding or "examined, nothing found".

| # | Angle | Scope |
|---|---|---|
| 1 | Line-by-line correctness | localized |
| 2 | Removed-behavior audit | localized |
| 3 | Cross-file tracer | cross-cutting |
| 4 | Publication & privacy boundary | cross-cutting, project-specific |
| 5 | Reuse / simplification / efficiency | localized |
| 6 | Conventions | localized |
| 7 | Overengineered for the current need | localized |
| 8 | Legitimacy of the carrying module | localized |
| 9 | Sibling-pattern | cross-cutting |
| 10 | Naming & vocabulary clarity | cross-cutting |

**Each angle's checklist and the required content of each kind of finding are
in [angles.md](angles.md).** Give every subagent that path and its angle
number(s) — don't paraphrase the checklist into the prompt.

## Step 4 — Verify before reporting

If Step 3 fanned out, merge and **dedupe** (two angles may flag the same line).
Merge the coverage manifests into one fraction per localized angle: hunks
examined ÷ total hunks (`grep -c '^@@'` on the diff). An incomplete sweep counts
against the total.

Drop any candidate on Step 2's "explicitly declined" list outright, unless the
code has moved past what the author decided.

Check every remaining candidate against the actual file and mark it:

- **CONFIRMED** — the exact line and the exact input that breaks it.
- **PLAUSIBLE** — real mechanism, but depends on something not verifiable here
  (a model's actual output, Discord or GitHub timing, scheduling under load).
- **REFUTED** — drop it. False-positive traps worth checking first:
  - Checks **pause** on `LLMUnavailable` while transcription continues — by
    design, not a swallowed error.
  - A contradiction is posted **once per subject** — the dedupe is intended.
  - Code repositories never back a contradiction and are never written to —
    their absence from fact-checking is intended.
  - Edit does nothing in replay; dry run (`DryRunPublisher`, `replay-out/`) is
    the default.
  - `FakeProvider` returns schema defaults and bag-of-words embeddings — it is
    a test double, not a degraded mode to harden.
  - The protocol is mirrored by hand on purpose; flag a divergence, not the
    duplication.
  - **Overengineered**: if your simpler version misses one of the concept's
    real edge cases, the complexity earns its keep. Diverging from an
    incidental choice the PR's tests assert is not a refutation — report the
    difference. Consistency with how the codebase already solves the same
    problem is not overengineering; anticipating a future need is out of scope.
  - **Legitimacy**: a module `CLAUDE.md` already makes the owner of a
    responsibility growing by a few lines is not misplacement.
  - **Naming**: no concrete future case on record → drop, don't downgrade.

Only CONFIRMED and PLAUSIBLE get posted. Keep it to what a reviewer can act on
in one pass (about 5-8 for a medium PR): rank by severity, cut the weakest nits
first.

## Step 5 — Assign severity

Prefix every comment body with one of these, exactly:

| Tag | When |
|---|---|
| `[HIGH]` | Deterministic break in a primary flow: the agent asserts something false in a meeting, private data or a token is published or logged, a meeting's minutes or decisions are lost, a crash on a normal path (start, segment, button, close, resume) |
| `[MEDIUM]` | Real bug or inconsistency on a less common path (an error branch, a resume, a reconnect, a race between a button and the consumer, a KB with unusual conventions), or doc drift on a behavior |
| `[LOW]` | Cleanup, convention deviation, naming or scoping hygiene, a plausible but speculative edge case |

**Overengineered**, **legitimacy** and **naming** findings are `[LOW]` unless
they break a `CLAUDE.md` rule (then the rule's severity) or already cause a
misreading inside this diff (then the bug's severity). A **sibling-pattern**
finding inherits the severity of the fixed original.

The tag goes **first**: `**[HIGH]** **Short title.** ...`

## Step 6 — Post as inline comments

Posting notifies everyone on the PR. If the user didn't explicitly ask for
comments to be posted, confirm first; if they did, proceed.

Write the payload to a JSON file in the scratchpad with the Write tool (quotes
and accents break shell quoting) and pass it with `--input`:

```json
{
  "commit_id": "<headRefOid from Step 1>",
  "event": "COMMENT",
  "body": "<1-3 sentence summary of the PR and what was checked>",
  "comments": [
    {
      "path": "src/kb_meeting_agent/agent/meeting.py",
      "line": 42,
      "side": "RIGHT",
      "body": "**[HIGH]** **Short title.** Concrete explanation with the scenario that triggers it.\n\n**Suggested fix**: what to change, concretely."
    }
  ]
}
```

```bash
gh api repos/<owner>/<repo>/pulls/<number>/reviews --input "$SCRATCHPAD/payload.json"
```

`line` must be in the diff (an added line, or a context line inside a changed
hunk); GitHub rejects others. Use `event: COMMENT` unless the user asks for a
blocking review.

## Step 7 — Editing posted comments

```bash
gh api repos/<owner>/<repo>/pulls/<number>/comments \
  --jq '.[] | select(.pull_request_review_id==<review_id>) | {id, path, line}'

gh api -X PATCH repos/<owner>/<repo>/pulls/comments/<comment_id> --input "$SCRATCHPAD/updated_body.json"
```

## Presenting the result

Reply with the review URL (returned by the POST) and a short ranked recap —
severity, `file:line`, one-line summary. If Step 2 found earlier rounds, say so
in one line ("3rd pass on this PR — X closed points not re-flagged, Y new"). If
Step 3 fanned out, give the coverage fraction per localized angle, labeled as
reading coverage, and explain any angle under 100%.
