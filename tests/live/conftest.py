import pytest

from kb_meeting_agent.config import AppConfig
from kb_meeting_agent.kb.repo import GitMarkdownKnowledgeBase
from kb_meeting_agent.live.session import MeetingSession, SessionDeps
from kb_meeting_agent.llm.fake import FAKE_DEFAULTS, FakeProvider
from kb_meeting_agent.publish.local import FakePublisher
from kb_meeting_agent.transcription.fake import FakeTranscriber
from live.helpers import Clock, FakeLink


@pytest.fixture
def make_session(tmp_path, kb_origin):
    def factory(*, fast=None, strong=None, live=None, final=None, publisher=None, **defaults):
        config = AppConfig.model_validate(
            {
                "agent_names": ["scribe"],
                "data_dir": str(tmp_path / "data"),
                "llm": {
                    role: {"provider": "fake", "model": "fake"}
                    for role in ("fast", "strong", "embedding")
                },
                "knowledge_bases": {"test": {"repo": "acme/kb", "clone_url": str(kb_origin)}},
                "defaults": {"auto_leave_empty_minutes": 0.001, **defaults},
                "transcription": {
                    "live": {"provider": "fake", "model": "fake"},
                    "min_utterance_seconds": 0,
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
            make_kb=lambda name, cfg: GitMarkdownKnowledgeBase(
                name, cfg, config.data_dir, FakeProvider().embed, "fake"
            ),
            make_publisher=lambda cfg: publisher,
            clock_ms=clock,
        )
        return MeetingSession(deps), link, clock, publisher

    return factory
