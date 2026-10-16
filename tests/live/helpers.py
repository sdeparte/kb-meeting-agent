from kb_meeting_agent.live.audio import BYTES_PER_MS
from kb_meeting_agent.live.protocol import AudioFrame


class FakeLink:
    def __init__(self):
        self.sent = []

    async def send(self, type_, **fields):
        self.sent.append((type_, fields))
        return True

    def of(self, type_):
        return [fields for kind, fields in self.sent if kind == type_]

    def texts(self):
        return [fields["text"] for fields in self.of("send")]


class Clock:
    def __init__(self, now=0):
        self.now = now

    def __call__(self):
        return self.now


def command(name, interaction="i1", user=("u1", "Alice"), voice="v1", **options):
    return {
        "type": "command",
        "interaction_id": interaction,
        "name": name,
        "options": options,
        "user": {"id": user[0], "name": user[1]},
        "text_channel_id": "t1",
        "voice_channel_id": voice,
    }


async def speak(session, user="u1", name="Alice", start=1_000, ms=1_000):
    await session.on_event(
        "message", {"type": "utterance_start", "user_id": user, "speaker_name": name, "t": start}
    )
    await session.on_event("audio", AudioFrame(user, start, bytes(BYTES_PER_MS * ms)))
    await session.on_event("message", {"type": "utterance_end", "user_id": user, "t": start + ms})
