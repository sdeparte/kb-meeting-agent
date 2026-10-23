"""The meeting commands, the same on every connector.

People type them in the meeting's chat (`!fin`, `!question …`); connectors with slash
commands and buttons build them from this catalog. Connectors never interpret a
command: they forward the line (a `chat` message) or the slash command, and the core parses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kb_meeting_agent.agent.messages import t

PREFIX = "!"
LEVELS = ("silent", "contradictions", "context")


@dataclass(frozen=True)
class Option:
    name: str
    description: str
    required: bool = True
    choices: tuple[str, ...] = ()
    rest: bool = False  # takes the rest of the line


@dataclass(frozen=True)
class Command:
    id: str
    words: tuple[str, ...]  # French first, English last: help and hints pick by language
    description: str  # English: slash command descriptions
    options: tuple[Option, ...] = ()
    slash: tuple[str, ...] | None = None


_PROJECT = Option("project", "Project name")
_DECISION = Option("decision", "Decision id, e.g. d1")

CATALOG: tuple[Command, ...] = (
    Command(
        "meeting_start",
        ("start",),
        "Transcribe your voice channel",
        (
            Option("project", "Project name", required=False),
            Option("level", "How often the agent speaks up", required=False, choices=LEVELS),
        ),
        ("meeting", "start"),
    ),
    Command(
        "meeting_project",
        ("projet", "project"),
        "Change the project before the agent has spoken",
        (_PROJECT,),
        ("meeting", "project"),
    ),
    Command(
        "meeting_end",
        ("fin", "end"),
        "End the meeting and publish the minutes",
        (),
        ("meeting", "end"),
    ),
    Command(
        "ask",
        ("question", "ask"),
        "Ask the agent about the project",
        (Option("question", "Your question", rest=True),),
        ("ask",),
    ),
    Command(
        "meeting_level",
        ("niveau", "level"),
        "Change how often the agent speaks up",
        (Option("level", "Level", choices=LEVELS),),
        ("meeting", "level"),
    ),
    Command(
        "meeting_optout", ("optout",), "Stop transcribing your voice", (), ("meeting", "optout")
    ),
    Command(
        "meeting_resume",
        ("reprendre", "resume"),
        "Resume the last unfinished meeting",
        (),
        ("meeting", "resume"),
    ),
    Command(
        "meeting_retry_publish",
        ("republier", "retry-publish"),
        "Publish pull requests kept after a failure",
        (),
        ("meeting", "retry-publish"),
    ),
    Command("decision_validate", ("valider", "validate"), "Validate a decision", (_DECISION,)),
    Command("decision_ignore", ("ignorer", "ignore"), "Ignore a decision", (_DECISION,)),
    Command(
        "decision_edit",
        ("modifier", "edit"),
        "Reword a decision, then validate it",
        (_DECISION, Option("statement", "The decision as it should read", rest=True)),
    ),
    Command("help", ("aide", "help"), "List the commands"),
)

_BY_WORD = {word: command for command in CATALOG for word in command.words}
_BUTTON_ACTIONS = {
    "validate": "decision_validate",
    "ignore": "decision_ignore",
    "edit": "decision_edit",
}


@dataclass(frozen=True)
class Parsed:
    id: str
    options: dict[str, str] = field(default_factory=dict)
    known: bool = True  # False for an unknown word: maybe another bot's command


_HELP = Parsed("help", {})


def parse(text: str) -> Parsed | None:
    """The command a chat line holds; None when it is not one, the help when it is invalid
    (flagged unknown when its word is not a command: other bots use `!` too)."""
    line = text.strip()
    if not line.startswith(PREFIX):
        return None
    tokens = line[len(PREFIX) :].split()
    command = _BY_WORD.get(tokens[0].casefold()) if tokens else None
    if command is None:
        return Parsed("help", {}, known=False) if tokens else _HELP
    args, options = tokens[1:], {}
    for option in command.options:
        value = " ".join(args) if option.rest else (args[0] if args else "")
        args = [] if option.rest else args[1:]
        if not value:
            if option.required:
                return _HELP
            continue
        if option.choices and value not in option.choices:
            return _HELP
        options[option.name] = value
    return _HELP if args else Parsed(command.id, options)


def _word(command: Command, lang: str) -> str:
    return command.words[0] if lang == "fr" else command.words[-1]


def typed(command_id: str, lang: str) -> str:
    """The command as typed in the chat, in the given language: `!reprendre`, `!resume`."""
    return PREFIX + _word(next(c for c in CATALOG if c.id == command_id), lang)


def _placeholder(option: Option, lang: str) -> str:
    name = t(lang, f"option_{option.name}")
    return f"<{name}>" if option.required else f"[{name}]"


def help_text(lang: str) -> str:
    lines = [t(lang, "help_header")]
    for command in CATALOG:
        usage = " ".join(
            [PREFIX + _word(command, lang), *(_placeholder(o, lang) for o in command.options)]
        )
        lines.append(f"`{usage}` — {t(lang, f'command_{command.id}')}")
    return "\n".join(lines)


def button_commands(button_id: str, lang: str) -> str | None:
    """What to type instead of clicking the button, for connectors without buttons."""
    prefix, _, rest = button_id.partition(":")
    decision, _, action = rest.partition(":")
    command_id = _BUTTON_ACTIONS.get(action)
    if prefix != "decision" or not decision or command_id is None:
        return None
    command = next(c for c in CATALOG if c.id == command_id)
    typed = f"{PREFIX}{_word(command, lang)} {decision}"
    if command_id == "decision_edit":
        typed += f" <{t(lang, 'option_statement')}>"
    return typed


def catalog_payload() -> list[dict[str, Any]]:
    """The commands a connector offers as slash commands, sent to it in a `commands` message."""
    return [
        {
            "id": command.id,
            "slash": list(command.slash),
            "description": command.description,
            "options": [
                {
                    "name": option.name,
                    "description": option.description,
                    "required": option.required,
                    "choices": list(option.choices),
                }
                for option in command.options
            ],
        }
        for command in CATALOG
        if command.slash is not None
    ]
