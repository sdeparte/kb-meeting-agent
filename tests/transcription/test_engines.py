from types import SimpleNamespace

import numpy as np

from kb_meeting_agent.config import TranscriberRole
from kb_meeting_agent.transcription.factory import build_transcriber
from kb_meeting_agent.transcription.fake import FakeTranscriber
from kb_meeting_agent.transcription.faster import FasterWhisperTranscriber
from kb_meeting_agent.transcription.mlx import MlxWhisperTranscriber
from kb_meeting_agent.transcription.openai_api import OpenAICompatibleTranscriber

AUDIO = np.zeros(1600, dtype=np.float32)


def test_mlx_whisper_passes_audio_prompt_and_language():
    calls = {}

    def transcribe(audio, **kwargs):
        calls.update(kwargs, n=len(audio))
        return {
            "text": " Bonjour ",
            "segments": [
                {"no_speech_prob": 0.3, "avg_logprob": -0.2},
                {"no_speech_prob": 0.1, "avg_logprob": -0.4},
            ],
        }

    role = TranscriberRole(provider="mlx-whisper", model="mlx-community/whisper-large-v3-turbo")
    result = MlxWhisperTranscriber(role, module=SimpleNamespace(transcribe=transcribe)).transcribe(
        AUDIO, language="fr", prompt="BIO-SCAN"
    )
    assert result.text == "Bonjour" and result.no_speech_prob == 0.1
    assert abs(result.avg_logprob - -0.3) < 1e-9
    assert calls["path_or_hf_repo"] == "mlx-community/whisper-large-v3-turbo"
    assert calls["language"] == "fr" and calls["initial_prompt"] == "BIO-SCAN"
    assert calls["condition_on_previous_text"] is False and calls["n"] == 1600


def test_faster_whisper_joins_segments():
    created = {}

    class Model:
        def __init__(self, name, **kwargs):
            created.update(kwargs, name=name)

        def transcribe(self, audio, **kwargs):
            created["transcribe"] = kwargs
            segments = [
                SimpleNamespace(text=" On passe", no_speech_prob=0.2, avg_logprob=-0.1),
                SimpleNamespace(text=" à 30. ", no_speech_prob=0.4, avg_logprob=-0.5),
            ]
            return iter(segments), None

    role = TranscriberRole(provider="faster-whisper", model="small", device="cpu", beam_size=5)
    result = FasterWhisperTranscriber(role, model_factory=Model).transcribe(
        AUDIO, language="fr", prompt=""
    )
    assert result.text == "On passe à 30." and result.no_speech_prob == 0.2
    assert abs(result.avg_logprob - -0.3) < 1e-9
    assert created["name"] == "small" and created["device"] == "cpu"
    assert created["compute_type"] == "int8"
    assert created["transcribe"]["beam_size"] == 5
    assert created["transcribe"]["initial_prompt"] is None


def test_openai_compatible_sends_a_wav_file():
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(text=" Salut ")

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    role = TranscriberRole(provider="openai-compatible", model="whisper-1", base_url="http://x/v1")
    result = OpenAICompatibleTranscriber(role, client=client).transcribe(
        AUDIO, language="fr", prompt="BIO-SCAN"
    )
    assert result.text == "Salut" and result.no_speech_prob is None
    name, data, mime = sent["file"]
    assert name.endswith(".wav") and data[:4] == b"RIFF" and mime == "audio/wav"
    assert (
        sent["model"] == "whisper-1" and sent["language"] == "fr" and sent["prompt"] == "BIO-SCAN"
    )


def test_factory_builds_the_fake():
    assert isinstance(
        build_transcriber(TranscriberRole(provider="fake", model="x")), FakeTranscriber
    )


def test_mlx_calls_are_serialised():
    import threading
    import time

    active, peak = 0, 0
    guard = threading.Lock()

    def transcribe(audio, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return {"text": "x", "segments": []}

    role = TranscriberRole(provider="mlx-whisper", model="m")
    engine = MlxWhisperTranscriber(role, module=SimpleNamespace(transcribe=transcribe))
    threads = [
        threading.Thread(
            target=engine.transcribe, args=(AUDIO,), kwargs={"language": None, "prompt": ""}
        )
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == 1
