import pytest

from kb_meeting_agent.config import AppConfig
from kb_meeting_agent.kb.project import build_sources
from kb_meeting_agent.live.session import MeetingSession, SessionDeps
from kb_meeting_agent.llm.fake import FAKE_DEFAULTS, FakeProvider
from kb_meeting_agent.publish.local import FakePublisher
from kb_meeting_agent.transcription.fake import FakeTranscriber
from live.helpers import Clock, FakeLink


@pytest.fixture
def make_session(tmp_path, kb_origin):
    def factory(
        *,
        fast=None,
        strong=None,
        live=None,
        final=None,
        publisher=None,
        agent=None,
        transcription=None,
        code=None,  # clone URL of a `back` CodeBase repository added to the project
        second_kb=None,  # clone URL of the KB of a second project, `other`
        **defaults,
    ):
        repos = {"kb": {"repo": "acme/kb", "clone_url": str(kb_origin), "tags": ["KnowledgeBase"]}}
        if code is not None:
            repos["back"] = {
                "repo": "acme/back",
                "clone_url": code,
                "tags": ["CodeBase", "BackEnd"],
            }
        config = AppConfig.model_validate(
            {
                "agent": agent or {"name": "Scribe"},
                "data_dir": str(tmp_path / "data"),
                "llm": {
                    role: {"provider": "fake", "model": "fake"}
                    for role in ("fast", "strong", "embedding")
                },
                "projects": {
                    "test": {"repos": repos},
                    **(
                        {
                            "other": {
                                "repos": {
                                    "kb2": {
                                        "repo": "acme/kb2",
                                        "clone_url": second_kb,
                                        "tags": ["KnowledgeBase"],
                                    }
                                }
                            }
                        }
                        if second_kb
                        else {}
                    ),
                },
                "defaults": {
                    "auto_leave_empty_minutes": 0.001,
                    **({"project": "test"} if second_kb else {}),
                    **defaults,
                },
                "transcription": {
                    "live": {"provider": "fake", "model": "fake"},
                    "min_utterance_seconds": 0,
                    "min_voiced_seconds": 0,
                    **(transcription or {}),
                },
            }
        )
        fast = fast or FakeProvider()
        strong = strong or FakeProvider()
        fast.defaults = FAKE_DEFAULTS | fast.defaults
        strong.defaults = FAKE_DEFAULTS | strong.defaults
        link = FakeLink()
        clock = Clock()
        publisher = publisher or FakePublisher()
        deps = SessionDeps(
            config=config,
            link=link,
            fast=fast,
            strong=strong,
            live_transcriber=live or FakeTranscriber(default="bonjour à tous"),
            final_transcriber=final,
            make_sources=lambda name, project: build_sources(
                name, project, config.data_dir, FakeProvider().embed, "fake"
            ),
            make_publisher=lambda cfg: publisher,
            clock_ms=clock,
        )
        return MeetingSession(deps), link, clock, publisher

    return factory
