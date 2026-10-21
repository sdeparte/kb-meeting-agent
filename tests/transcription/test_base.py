import numpy as np

from kb_meeting_agent.transcription.base import (
    HallucinationFilter,
    TranscriptionResult,
    float_to_pcm16,
    pcm16_to_float,
    read_wav,
    vocabulary_prompt,
    voiced_seconds,
    write_wav,
)
from kb_meeting_agent.transcription.fake import FakeTranscriber

GLOSSARY = """# Glossaire

| In-fiction | Code |
|---|---|
| BIO-SCAN | `biometric` |
| **Brouillage** | `jammed` |

Le seuil `RSSI_PROXIMITY_THRESHOLD` vit dans la configuration.
"""


def test_pcm_round_trip_and_wav(tmp_path):
    pcm = np.array([0, 16384, -16384, 32767], dtype="<i2").tobytes()
    audio = pcm16_to_float(pcm)
    assert audio.dtype == np.float32
    assert abs(audio[1] - 0.5) < 1e-6
    assert float_to_pcm16(audio) == np.array([0, 16384, -16384, 32766], dtype="<i2").tobytes()
    write_wav(tmp_path / "a.wav", pcm)
    assert read_wav(tmp_path / "a.wav") == pcm


def test_vocabulary_prompt_extracts_terms_and_skips_headers():
    prompt = vocabulary_prompt(GLOSSARY, 600)
    assert prompt == "BIO-SCAN, Brouillage, biometric, jammed"
    assert vocabulary_prompt(GLOSSARY, 20) == "BIO-SCAN, Brouillage"
    assert vocabulary_prompt("", 600) == ""


def test_vocabulary_prompt_puts_first_terms_ahead():
    assert vocabulary_prompt(GLOSSARY, 600, first=["Otis", "KB", "BIO-SCAN"]) == (
        "Otis, KB, BIO-SCAN, Brouillage, biometric, jammed"
    )
    assert vocabulary_prompt("", 600, first=["Otis"]) == "Otis"


def test_vocabulary_prompt_leaves_out_what_nobody_says():
    glossary = """> Relu sur `main` @ `4978b63` (`lib/l10n/app_fr.arb`).

| Terme | Définition | Code |
|---|---|---|
| **[PROD]** | statut | — |
| **Attente serveur (pending)** | relu @ `08d77ea` | `showPending`, `PendingLayer`, `AppDurations.pendingSlowTier` |
| **CAS** | boucle `PlayerMutator::mutate()`, route `beacon/scan` | `status_effect` |
| **Corpo** | faction | `impostor` |
"""
    assert vocabulary_prompt(glossary, 600) == "Attente serveur (pending), CAS, Corpo, impostor"


def test_hallucination_filter():
    clean = HallucinationFilter(["Abonnez-vous"], min_seconds=0.4, max_no_speech_prob=0.6).clean
    assert clean(TranscriptionResult("On passe à 30 secondes."), 2.0) == "On passe à 30 secondes."
    assert (
        clean(TranscriptionResult("Sous-titres réalisés par la communauté d’Amara.org"), 2.0)
        is None
    )
    assert clean(TranscriptionResult("Bon. Abonnez-vous !"), 2.0) == "Bon"
    assert clean(TranscriptionResult("Oui"), 0.2) is None
    assert clean(TranscriptionResult("Hmm", no_speech_prob=0.9), 2.0) is None
    assert clean(TranscriptionResult("Oui", no_speech_prob=0.1), 2.0) == "Oui"
    assert clean(TranscriptionResult("Merci."), 2.0) is None
    assert clean(TranscriptionResult("Thank you!"), 2.0) is None
    assert clean(TranscriptionResult("Merci Nicolas."), 2.0) == "Merci Nicolas."


def test_hallucination_phrases_inside_a_sentence_are_speech():
    clean = HallucinationFilter([], min_seconds=0.4, max_no_speech_prob=0.6).clean
    kept = "Merci d'avoir regardé la PR, on peut merger."
    assert clean(TranscriptionResult(kept), 2.0) == kept
    kept = "Thanks for watching the demo, next item"
    assert clean(TranscriptionResult(kept), 2.0) == kept
    said = "On passe au point suivant. Merci d'avoir regardé cette vidéo."
    assert clean(TranscriptionResult(said), 2.0) == "On passe au point suivant"
    assert clean(TranscriptionResult("Thanks for watching! Next item."), 2.0) == "Next item"


def test_hallucination_filter_confidence_and_silence():
    cleaner = HallucinationFilter([], 0.4, 0.6, min_voiced_seconds=0.2, min_avg_logprob=-1.0)
    assert cleaner.clean(TranscriptionResult("Melume ...", avg_logprob=-2.2), 2.0) is None
    assert cleaner.clean(TranscriptionResult("Ça va ?", avg_logprob=-0.3), 2.0) == "Ça va ?"
    silence = np.full(8000, 0.001, dtype=np.float32)  # -60 dBFS, half a second
    speech = np.concatenate([silence, np.full(8000, 0.1, dtype=np.float32)])
    assert voiced_seconds(silence) == 0 and voiced_seconds(speech) == 0.5
    assert not cleaner.audible(silence) and cleaner.audible(speech)


def test_fake_transcriber_records_calls():
    fake = FakeTranscriber(["un", TranscriptionResult("deux", 0.2)], default="encore")
    audio = np.zeros(16000, dtype=np.float32)
    assert fake.transcribe(audio, language="fr", prompt="BIO-SCAN").text == "un"
    assert fake.transcribe(audio, language="fr", prompt="").no_speech_prob == 0.2
    assert fake.transcribe(audio, language=None, prompt="").text == "encore"
    assert fake.calls[0] == (16000, "fr", "BIO-SCAN")
