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
        "decision_draft_failed": (
            "Could not write the decision record: the model did not give a usable answer (for "
            "example a scope outside the KB's list). Nothing was published; validate again to "
            "retry."
        ),
        "level_changed": "Intervention level: {level}.",
        "checks_paused": "Checks paused: the model is unavailable. Transcription continues.",
        "checks_resumed": "Checks resumed.",
        "meeting_resumed": "Meeting resumed.",
        "nothing_to_resume": "There is no unfinished meeting to resume.",
        "retry_publish_done": "Published {count} kept pull request(s): {urls}",
        "retry_publish_none": "Nothing to publish.",
        "close_failed": (
            "Ending the meeting failed: no minutes were published. The transcript is kept on "
            "the agent's machine; details are in its log."
        ),
        "recording_notice": (
            "This meeting is transcribed by an AI agent. Audio stays on the agent's machine "
            "until the minutes are published, then it is deleted. The minutes and the validated "
            "decisions will be proposed as pull requests in {repo}. Use /meeting optout to stop "
            "transcribing your voice."
        ),
        "meeting_started": "Meeting started with the {kb} knowledge base.",
        "meeting_already_running": "A meeting is already running.",
        "join_voice_first": "Join a voice channel first.",
        "unknown_kb": "Unknown knowledge base. Available: {names}.",
        "no_meeting": "No meeting is running.",
        "meeting_ending": "Ending the meeting: writing the minutes…",
        "meeting_already_ending": "The meeting is already ending.",
        "optout_done": (
            "Your voice is no longer transcribed in this meeting and your recorded audio was "
            "deleted. What you said before stays in the transcript."
        ),
        "command_failed": "The command failed; details are in the agent's log.",
        "unknown_command": "Unknown command.",
        "transcription_lag": "Transcription is running {seconds} s behind.",
        "audio_interrupted": "Audio was interrupted from {start} to {end}.",
        "edit_title": "Edit the decision",
        "edit_label": "Decision",
        "decision_number_taken": (
            "Decision {number:04d} is now used on the base branch: {url} needs a new number "
            "before it can be merged."
        ),
        "decision_branch_changed": (
            "{url} was changed by someone else during the meeting; the agent left it as is."
        ),
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
        "decision_draft_failed": (
            "Impossible de rédiger la fiche de décision : le modèle n'a pas donné de réponse "
            "exploitable (par exemple un périmètre hors de la liste de la KB). Rien n'a été "
            "publié ; validez à nouveau pour réessayer."
        ),
        "level_changed": "Niveau d'intervention : {level}.",
        "checks_paused": (
            "Vérifications en pause : le modèle est indisponible. La transcription continue."
        ),
        "checks_resumed": "Vérifications reprises.",
        "meeting_resumed": "Réunion reprise.",
        "nothing_to_resume": "Aucune réunion inachevée à reprendre.",
        "retry_publish_done": "{count} pull request(s) conservée(s) publiée(s) : {urls}",
        "retry_publish_none": "Rien à publier.",
        "close_failed": (
            "La clôture de la réunion a échoué : aucun compte rendu n'a été publié. La "
            "transcription est conservée sur la machine de l'agent ; le détail est dans son journal."
        ),
        "recording_notice": (
            "Cette réunion est transcrite par un agent IA. L'audio reste sur la machine de "
            "l'agent jusqu'à la publication du compte rendu, puis il est supprimé. Le compte "
            "rendu et les décisions validées seront proposés en pull request dans {repo}. "
            "Utilisez /meeting optout pour ne plus être transcrit."
        ),
        "meeting_started": "Réunion démarrée avec la base de connaissances {kb}.",
        "meeting_already_running": "Une réunion est déjà en cours.",
        "join_voice_first": "Rejoignez d'abord un salon vocal.",
        "unknown_kb": "Base de connaissances inconnue. Disponibles : {names}.",
        "no_meeting": "Aucune réunion en cours.",
        "meeting_ending": "Clôture de la réunion : rédaction du compte rendu…",
        "meeting_already_ending": "La réunion est déjà en cours de clôture.",
        "optout_done": (
            "Votre voix n'est plus transcrite dans cette réunion et votre audio enregistré a été "
            "supprimé. Ce que vous avez dit avant reste dans la transcription."
        ),
        "command_failed": "La commande a échoué ; le détail est dans le journal de l'agent.",
        "unknown_command": "Commande inconnue.",
        "transcription_lag": "La transcription a {seconds} s de retard.",
        "audio_interrupted": "L'audio a été interrompu de {start} à {end}.",
        "edit_title": "Modifier la décision",
        "edit_label": "Décision",
        "decision_number_taken": (
            "Le numéro {number:04d} est désormais pris sur la branche de base : {url} doit être "
            "renumérotée avant d'être mergée."
        ),
        "decision_branch_changed": (
            "{url} a été modifiée par quelqu'un d'autre pendant la réunion ; l'agent n'y a pas "
            "touché."
        ),
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
