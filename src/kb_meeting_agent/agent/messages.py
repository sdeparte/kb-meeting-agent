from __future__ import annotations

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "help_header": "Commands (type them in the chat):",
        "project_changed": "Project changed: {project}.",
        "project_locked": (
            "The project can no longer change: the agent has already spoken. Project: {project}."
        ),
        "decision_reply_hint": "Reply {commands}.",
        "option_project": "project",
        "option_level": "level",
        "option_question": "question",
        "option_decision": "decision",
        "option_statement": "statement",
        "command_meeting_start": "start the meeting, from the call",
        "command_meeting_project": "change the project, before the agent has said anything",
        "command_meeting_end": "end the meeting and publish the minutes",
        "command_ask": "ask the agent about the project",
        "command_meeting_level": "how often the agent speaks up (silent, contradictions, context)",
        "command_meeting_optout": "stop transcribing your voice",
        "command_meeting_resume": "resume the last unfinished meeting",
        "command_meeting_retry_publish": "publish the pull requests kept after a failure",
        "command_decision_validate": "validate a proposed decision",
        "command_decision_ignore": "ignore a proposed decision",
        "command_decision_edit": "reword a proposed decision, then validate it",
        "command_help": "list the commands",
        "answer": "{answer}\n\nSources: {sources}",
        "not_covered": "The KB does not cover this point.",
        "contradiction": "The KB says “{quote}” ({anchor}). {reason}",
        "already_rejected": "This was already rejected in the KB: “{quote}” ({anchor}). {reason}",
        "stale": " Note: this page was last verified on {date}.",
        "context": "Related KB page: {anchor}",
        "decision_detected": "Decision {id} detected: *{statement}*",
        "decision_published": "Decision validated by {user}: {url}",
        "announce_searching": "🔎 Searching the KB: “{question}”",
        "announce_validating": (
            "✍️ {user} validated “{statement}”: drafting the decision record and opening "
            "the pull request…"
        ),
        "announce_failed": (
            "Interrupted: the model did not answer (the agent's log has the details). "
            "Try again in a moment."
        ),
        "announce_error": "Interrupted by an error (the agent's log has the details).",
        "decision_ignored": "Decision ignored by {user}.",
        "decision_draft_failed": (
            "Could not write the decision record: the model did not give a usable answer (the "
            "agent's log has the details). Nothing was published; validate again to retry."
        ),
        "level_changed": "Intervention level: {level}.",
        "checks_paused": "Checks paused: the model is unavailable. Transcription continues.",
        "checks_resumed": "Checks resumed.",
        "agent_label": "{name} (AI)",
        "meeting_resumed": "Meeting resumed.",
        "resume_offer": (
            "A meeting on the {project} project was interrupted in this call: type `{resume}` "
            "to resume it, or `{start}` again to start a new meeting."
        ),
        "nothing_to_resume": "There is no unfinished meeting to resume.",
        "retry_publish_done": "Published {count} kept pull request(s): {urls}",
        "retry_publish_none": "Nothing to publish.",
        "retry_publish_number_taken": (
            "Not published: decision number {number:04d} is now used in the KB ({branch}). "
            "Its files stay in the agent's data folder."
        ),
        "close_failed": (
            "Ending the meeting failed: no minutes were published. The transcript is kept on "
            "the agent's machine; details are in its log."
        ),
        "recording_notice": (
            "This meeting is transcribed by {name}, an AI agent. Say “{name}, …” to ask it a "
            "question. Audio stays on the agent's machine until the minutes are published, then "
            "it is deleted. The minutes and the validated decisions will be proposed as pull "
            "requests in {repo}. Project: {project} (!project <name> changes it until the agent "
            "speaks). Type !optout to stop transcribing your voice; !help lists the commands."
        ),
        "meeting_started": "Meeting started with the {project} project.",
        "meeting_already_running": "A meeting is already running.",
        "join_voice_first": "Join a voice channel first.",
        "unknown_project": "Unknown project. Available: {names}.",
        "code_index_building": (
            "Building the index of {repo}: answers about its code will improve once it is ready."
        ),
        "code_repo_unavailable": (
            "The {repo} repository is unavailable: answers rely on the other sources."
        ),
        "no_meeting": "No meeting is running.",
        "meeting_ending": "Ending the meeting: writing the minutes…",
        "meeting_already_ending": "The meeting is already ending.",
        "optout_done": (
            "Your voice is no longer transcribed in this meeting and your recorded audio was "
            "deleted. What you said before stays in the transcript."
        ),
        "command_failed": "The command failed; details are in the agent's log.",
        "unknown_command": "Unknown command.",
        "not_in_meeting": (
            "Only the meeting's participants can do that: join its call or use its text channel."
        ),
        "unknown_decision": "No pending decision {decision}. Pending: {pending}.",
        "no_pending_decision": "none",
        "transcription_lag": "Transcription is running {seconds} s behind.",
        "audio_interrupted": "Audio was interrupted from {start} to {end}.",
        "invite_agent_again": (
            "I am no longer in the call and cannot rejoin it on my own: invite me again to go on."
        ),
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
        "decision_pr_code": "\n## Code files that may be affected\n\n{items}\n",
        "minutes_pr_title": "Minutes: {title}",
        "minutes_pr_body": "Minutes of the meeting of {date}. Participants: {participants}.",
        "someone": "Someone",
        "record_proposed": "{agent} proposed the decision “{statement}”",
        "record_contradiction": "{agent} pointed out that “{statement}” contradicts the KB: “{quote}” ({anchor})",
        "record_already_rejected": (
            "{agent} pointed out that “{statement}” was already rejected in the KB: “{quote}” ({anchor})"
        ),
        "record_context": "{agent} pointed to the KB page {anchor}",
        "record_answer": "{user} asked {agent}: “{question}”; answer: “{answer}”",
        "record_level": "{user} set {agent} to the `{level}` level",
        "record_reworded": "{user} reworded the decision “{before}” as “{after}”",
        "record_dismissed": "{user} dismissed the decision “{statement}”",
        "record_validated": "{user} validated the decision “{statement}” ({url})",
        "record_validated_kept": (
            "{user} validated the decision “{statement}” (publication failed, kept locally)"
        ),
        "minutes_participants": "Participants",
        "minutes_agenda": "Agenda",
        "minutes_discussion": "Discussion",
        "minutes_decisions": "Decisions",
        "minutes_decision_kept": "validated, pull request not published yet",
        "minutes_pending": "Decisions awaiting validation",
        "minutes_not_retained": "Decisions proposed but not retained",
        "minutes_contradictions": "Contradictions with the KB",
        "minutes_contradicts": "the KB says",
        "minutes_already_rejected": "already rejected in the KB",
        "minutes_actions": "Action items",
        "minutes_questions": "Open questions",
        "minutes_gaps": "Transcription gaps",
    },
    "fr": {
        "help_header": "Commandes (à taper dans le chat) :",
        "project_changed": "Projet changé : {project}.",
        "project_locked": (
            "Le projet ne peut plus changer : l'agent a déjà parlé. Projet : {project}."
        ),
        "decision_reply_hint": "Répondez {commands}.",
        "option_project": "projet",
        "option_level": "niveau",
        "option_question": "question",
        "option_decision": "décision",
        "option_statement": "énoncé",
        "command_meeting_start": "démarrer la réunion, depuis l'appel",
        "command_meeting_project": "changer de projet, avant que l'agent ait parlé",
        "command_meeting_end": "terminer la réunion et publier le compte rendu",
        "command_ask": "poser une question sur le projet",
        "command_meeting_level": "fréquence des interventions (silent, contradictions, context)",
        "command_meeting_optout": "ne plus transcrire votre voix",
        "command_meeting_resume": "reprendre la dernière réunion inachevée",
        "command_meeting_retry_publish": "publier les pull requests gardées après un échec",
        "command_decision_validate": "valider une décision proposée",
        "command_decision_ignore": "ignorer une décision proposée",
        "command_decision_edit": "reformuler une décision proposée, puis la valider",
        "command_help": "lister les commandes",
        "answer": "{answer}\n\nSources : {sources}",
        "not_covered": "La KB ne couvre pas ce point.",
        "contradiction": "La KB indique « {quote} » ({anchor}). {reason}",
        "already_rejected": "Déjà écarté dans la KB : « {quote} » ({anchor}). {reason}",
        "stale": " Attention : page vérifiée pour la dernière fois le {date}.",
        "context": "Page de la KB liée : {anchor}",
        "decision_detected": "Décision {id} détectée : *{statement}*",
        "decision_published": "Décision validée par {user} : {url}",
        "announce_searching": "🔎 Je cherche dans la KB : « {question} »",
        "announce_validating": (
            "✍️ {user} a validé « {statement} » : je rédige la fiche de décision et j'ouvre "
            "la pull request…"
        ),
        "announce_failed": (
            "Interrompu : le modèle n'a pas répondu (détails dans le journal de l'agent). "
            "Réessayez dans un instant."
        ),
        "announce_error": "Interrompu par une erreur (détails dans le journal de l'agent).",
        "decision_ignored": "Décision ignorée par {user}.",
        "decision_draft_failed": (
            "Impossible de rédiger la fiche de décision : le modèle n'a pas donné de réponse "
            "exploitable (détails dans le journal de l'agent). Rien n'a été publié ; validez à "
            "nouveau pour réessayer."
        ),
        "level_changed": "Niveau d'intervention : {level}.",
        "checks_paused": (
            "Vérifications en pause : le modèle est indisponible. La transcription continue."
        ),
        "checks_resumed": "Vérifications reprises.",
        "agent_label": "{name} (IA)",
        "meeting_resumed": "Réunion reprise.",
        "resume_offer": (
            "Une réunion sur le projet {project} a été interrompue dans cet appel : tapez "
            "`{resume}` pour la reprendre, ou `{start}` à nouveau pour en commencer une nouvelle."
        ),
        "nothing_to_resume": "Aucune réunion inachevée à reprendre.",
        "retry_publish_done": "{count} pull request(s) conservée(s) publiée(s) : {urls}",
        "retry_publish_none": "Rien à publier.",
        "retry_publish_number_taken": (
            "Non publiée : le numéro de décision {number:04d} est désormais pris dans la KB "
            "({branch}). Ses fichiers restent dans le dossier de données de l'agent."
        ),
        "close_failed": (
            "La clôture de la réunion a échoué : aucun compte rendu n'a été publié. La "
            "transcription est conservée sur la machine de l'agent ; le détail est dans son journal."
        ),
        "recording_notice": (
            "Cette réunion est transcrite par {name}, un agent IA. Dites « {name}, … » pour lui "
            "poser une question. L'audio reste sur la machine de l'agent jusqu'à la publication "
            "du compte rendu, puis il est supprimé. Le compte rendu et les décisions validées "
            "seront proposés en pull request dans {repo}. Projet : {project} (!projet <nom> en "
            "change tant que l'agent n'a pas parlé). Tapez !optout pour ne plus être transcrit ; "
            "!aide liste les commandes."
        ),
        "meeting_started": "Réunion démarrée avec le projet {project}.",
        "meeting_already_running": "Une réunion est déjà en cours.",
        "join_voice_first": "Rejoignez d'abord un salon vocal.",
        "unknown_project": "Projet inconnu. Disponibles : {names}.",
        "code_index_building": (
            "Construction de l'index de {repo} : les réponses sur son code s'amélioreront "
            "une fois l'index prêt."
        ),
        "code_repo_unavailable": (
            "Le dépôt {repo} est indisponible : les réponses s'appuient sur les autres sources."
        ),
        "no_meeting": "Aucune réunion en cours.",
        "meeting_ending": "Clôture de la réunion : rédaction du compte rendu…",
        "meeting_already_ending": "La réunion est déjà en cours de clôture.",
        "optout_done": (
            "Votre voix n'est plus transcrite dans cette réunion et votre audio enregistré a été "
            "supprimé. Ce que vous avez dit avant reste dans la transcription."
        ),
        "command_failed": "La commande a échoué ; le détail est dans le journal de l'agent.",
        "unknown_command": "Commande inconnue.",
        "not_in_meeting": (
            "Seuls les participants de la réunion peuvent faire cela : rejoignez son appel ou "
            "utilisez son salon texte."
        ),
        "unknown_decision": "Aucune décision {decision} en attente. En attente : {pending}.",
        "no_pending_decision": "aucune",
        "transcription_lag": "La transcription a {seconds} s de retard.",
        "audio_interrupted": "L'audio a été interrompu de {start} à {end}.",
        "invite_agent_again": (
            "Je ne suis plus dans l'appel et ne peux pas le rejoindre seul : invitez-moi de nouveau "
            "pour continuer."
        ),
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
        "decision_pr_code": "\n## Fichiers de code qui semblent concernés\n\n{items}\n",
        "minutes_pr_title": "Compte rendu : {title}",
        "minutes_pr_body": "Compte rendu de la réunion du {date}. Participants : {participants}.",
        "someone": "Quelqu'un",
        "record_proposed": "{agent} a proposé la décision « {statement} »",
        "record_contradiction": (
            "{agent} a signalé que « {statement} » contredit la KB : « {quote} » ({anchor})"
        ),
        "record_already_rejected": (
            "{agent} a signalé que « {statement} » a déjà été écarté dans la KB : « {quote} » ({anchor})"
        ),
        "record_context": "{agent} a indiqué la page de la KB {anchor}",
        "record_answer": "{user} a demandé à {agent} : « {question} » ; réponse : « {answer} »",
        "record_level": "{user} a réglé {agent} sur le niveau `{level}`",
        "record_reworded": "{user} a reformulé la décision « {before} » en « {after} »",
        "record_dismissed": "{user} a écarté la décision « {statement} »",
        "record_validated": "{user} a validé la décision « {statement} » ({url})",
        "record_validated_kept": (
            "{user} a validé la décision « {statement} » (publication échouée, gardée en local)"
        ),
        "minutes_participants": "Participants",
        "minutes_agenda": "Ordre du jour",
        "minutes_discussion": "Discussion",
        "minutes_decisions": "Décisions",
        "minutes_decision_kept": "validée, pull request pas encore publiée",
        "minutes_pending": "Décisions en attente de validation",
        "minutes_not_retained": "Décisions proposées non retenues",
        "minutes_contradictions": "Contradictions avec la KB",
        "minutes_contradicts": "la KB dit",
        "minutes_already_rejected": "déjà écarté dans la KB",
        "minutes_actions": "Actions",
        "minutes_questions": "Questions ouvertes",
        "minutes_gaps": "Trous de transcription",
    },
}


def t(language: str, key: str, **values: object) -> str:
    table = _MESSAGES.get(language, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**values)
