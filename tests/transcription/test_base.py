import numpy as np

from kb_meeting_agent.transcription.base import (
    HallucinationFilter,
    TranscriptionResult,
    float_to_pcm16,
    pcm16_to_float,
    read_wav,
    vocabulary_prompt,
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
    assert prompt == "BIO-SCAN, biometric, Brouillage, jammed, RSSI_PROXIMITY_THRESHOLD"
    assert vocabulary_prompt(GLOSSARY, 20) == "BIO-SCAN, biometric"
    assert vocabulary_prompt("", 600) == ""


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


def test_fake_transcriber_records_calls():
    fake = FakeTranscriber(["un", TranscriptionResult("deux", 0.2)], default="encore")
    audio = np.zeros(16000, dtype=np.float32)
    assert fake.transcribe(audio, language="fr", prompt="BIO-SCAN").text == "un"
    assert fake.transcribe(audio, language="fr", prompt="").no_speech_prob == 0.2
    assert fake.transcribe(audio, language=None, prompt="").text == "encore"
    assert fake.calls[0] == (16000, "fr", "BIO-SCAN")
