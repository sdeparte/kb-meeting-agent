from __future__ import annotations

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "answer": "{answer}\n\nSources: {sources}",
        "not_covered": "The KB does not cover this point.",
        "contradiction": "The KB says “{quote}” ({anchor}). {reason}",
        "already_rejected": "This was already rejected in the KB: “{quote}” ({anchor}). {reason}",
        "stale": " Note: this page was last verified on {date}.",
        "context": "Related KB page: {anchor}",
        "decision_detected": "Decision detected: *{statement}*",
        "decision_published": "Decision validated by {user}: {url}",
        "decision_ignored": "Decision ignored by {user}.",
        "level_changed": "Intervention level: {level}.",
        "checks_paused": "Checks paused: the model is unavailable. Transcription continues.",
        "checks_resumed": "Checks resumed.",
        "model_rejected": "The model rejected the request ({error}). Check the model configuration.",
        "excerpt_unanchored": (
            "The decision could not be matched to an exact line; transcript around it:"
        ),
        "minutes_published": "Meeting minutes: {url}",
        "publish_failed": "Publishing failed: {error}",
        "kept_locally": (
            "Publishing failed: {error}. The files are kept on the agent's machine, in the "
            "meeting's unpublished/ folder."
        ),
        "minutes_failed": (
            "Could not write the minutes ({error}). The transcript is kept on the agent's "
            "machine (transcript.jsonl in the meeting folder)."
        ),
        "button_validate": "Validate",
        "button_edit": "Edit",
        "button_ignore": "Ignore",
        "decision_sources": "Meeting of {date}, validated by {user}.",
        "decision_pr_title": "Decision: {title}",
        "decision_pr_body": (
            "Decision validated by {user} during the meeting of {date}.\n\n"
            "## Transcript excerpt\n\n{quote}\n\n"
            "## Pages that may need an update\n\n{related}\n"
        ),
        "no_related_pages": "None identified.",
        "minutes_pr_title": "Minutes: {title}",
        "minutes_pr_body": "Minutes of the meeting of {date}. Participants: {participants}.",
    },
    "fr": {
        "answer": "{answer}\n\nSources : {sources}",
        "not_covered": "La KB ne couvre pas ce point.",
        "contradiction": "La KB indique « {quote} » ({anchor}). {reason}",
        "already_rejected": "Déjà écarté dans la KB : « {quote} » ({anchor}). {reason}",
        "stale": " Attention : page vérifiée pour la dernière fois le {date}.",
        "context": "Page de la KB liée : {anchor}",
        "decision_detected": "Décision détectée : *{statement}*",
        "decision_published": "Décision validée par {user} : {url}",
        "decision_ignored": "Décision ignorée par {user}.",
        "level_changed": "Niveau d'intervention : {level}.",
        "checks_paused": (
            "Vérifications en pause : le modèle est indisponible. La transcription continue."
        ),
        "checks_resumed": "Vérifications reprises.",
        "model_rejected": "Le modèle a refusé la requête ({error}). Vérifier sa configuration.",
        "excerpt_unanchored": (
            "La décision n'a pas pu être rattachée à une ligne précise ; transcription autour :"
        ),
        "minutes_published": "Compte rendu : {url}",
        "publish_failed": "Échec de la publication : {error}",
        "kept_locally": (
            "Échec de la publication : {error}. Les fichiers sont conservés sur la machine de "
            "l'agent, dans le dossier unpublished/ de la réunion."
        ),
        "minutes_failed": (
            "Impossible de rédiger le compte rendu ({error}). La transcription est conservée sur "
            "la machine de l'agent (transcript.jsonl dans le dossier de la réunion)."
        ),
        "button_validate": "Valider",
        "button_edit": "Modifier",
        "button_ignore": "Ignorer",
        "decision_sources": "Réunion du {date}, décision validée par {user}.",
        "decision_pr_title": "Décision : {title}",
        "decision_pr_body": (
            "Décision validée par {user} pendant la réunion du {date}.\n\n"
            "## Extrait de la transcription\n\n{quote}\n\n"
            "## Pages qui semblent concernées\n\n{related}\n"
        ),
        "no_related_pages": "Aucune identifiée.",
        "minutes_pr_title": "Compte rendu : {title}",
        "minutes_pr_body": "Compte rendu de la réunion du {date}. Participants : {participants}.",
    },
}


def t(language: str, key: str, **values: object) -> str:
    table = _MESSAGES.get(language, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**values)
