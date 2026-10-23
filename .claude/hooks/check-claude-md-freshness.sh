#!/bin/bash
# PreToolUse hook (Bash matcher, filtered to `gh pr create`).
# Heuristic nudge only — never blocks. Flags likely CLAUDE.md drift so Claude
# considers running the evolve-project-config skill before a PR is opened,
# instead of docs silently rotting across several merged branches.
set -eu
(set -o pipefail) 2>/dev/null && set -o pipefail || true

INPUT=$(cat)
if command -v jq >/dev/null 2>&1; then
  CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
else
  CMD=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null || true)
fi

case "$CMD" in
  *"gh pr create"*) ;;
  *) exit 0 ;;
esac

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$REPO_ROOT"

BASE=$(git merge-base origin/main HEAD 2>/dev/null || git merge-base main HEAD 2>/dev/null) || exit 0
[ -z "$BASE" ] && exit 0

# Already touched CLAUDE.md on this branch — nothing to nudge about.
DOCS_TOUCHED=$(git diff --name-only "$BASE"..HEAD -- CLAUDE.md 2>/dev/null)
[ -n "$DOCS_TOUCHED" ] && exit 0

SIGNALS=()

# New Python dependency or extra.
if git diff "$BASE"..HEAD -- pyproject.toml 2>/dev/null | grep -qE '^\+\s+"[A-Za-z0-9_.-]+(\[[^]]*\])?\s*[<>=~!]'; then
  SIGNALS+=("new pyproject.toml dependency")
fi

# New connector dependency.
if git diff "$BASE"..HEAD -- connector-discord/package.json 2>/dev/null | grep -qE '^\+\s+"[@a-z0-9/._-]+":\s*"\^?[0-9]'; then
  SIGNALS+=("new connector-discord dependency")
fi

# New CLI subcommand.
if git diff "$BASE"..HEAD -- src/kb_meeting_agent/cli.py 2>/dev/null | grep -qE '^\+.*add_parser\('; then
  SIGNALS+=("new CLI subcommand")
fi

# Port or connector protocol changed.
CONTRACTS=$(git diff --name-only "$BASE"..HEAD -- src/kb_meeting_agent/ports.py src/kb_meeting_agent/live/protocol.py connector-discord/src/protocol.js 2>/dev/null)
[ -n "$CONTRACTS" ] && SIGNALS+=("port or protocol changed: $(echo $CONTRACTS)")

# New package under src/kb_meeting_agent/.
NEW_PACKAGES=$(git diff --name-only --diff-filter=A "$BASE"..HEAD -- 'src/kb_meeting_agent/*/__init__.py' 2>/dev/null)
[ -n "$NEW_PACKAGES" ] && SIGNALS+=("new package(s): $(echo $NEW_PACKAGES)")

# New provider or engine module.
NEW_PROVIDERS=$(git diff --name-only --diff-filter=A "$BASE"..HEAD -- src/kb_meeting_agent/llm src/kb_meeting_agent/transcription src/kb_meeting_agent/publish 2>/dev/null)
[ -n "$NEW_PROVIDERS" ] && SIGNALS+=("new provider/engine/publisher: $(echo $NEW_PROVIDERS)")

[ ${#SIGNALS[@]} -eq 0 ] && exit 0

JOINED=$(printf '; %s' "${SIGNALS[@]}")
REASON="Possible CLAUDE.md drift on this branch (${JOINED:2}) — consider running the evolve-project-config skill before opening this PR."
if command -v jq >/dev/null 2>&1; then
  jq -n --arg reason "$REASON" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $reason}}'
else
  python3 -c "import json,sys; print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'additionalContext': sys.argv[1]}}))" "$REASON"
fi
