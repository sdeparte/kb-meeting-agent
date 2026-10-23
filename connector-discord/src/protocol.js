// Connector <-> core protocol, version 2. Mirrors src/kb_meeting_agent/live/protocol.py.
// Ids (users, channels, interactions) are opaque strings: here, Discord snowflakes. A user has
// one id: the userId of audio frames and `speaking` is the user.id of interactions (opt-out).
export const PROTOCOL_VERSION = 2;
// Exit code when the env is refused (a missing credential): the core does not restart us
export const CONFIG_ERROR_EXIT = 78;
export const AUDIO_FRAME = 0x01;
// kind (1 byte), timestamp (8), length of the user id (1); then the id (UTF-8), then the PCM
const HEADER_SIZE = 10;
const MAX_ID_BYTES = 255;

export function encodeAudioFrame(userId, timestampMs, pcm) {
  const id = Buffer.from(String(userId), "utf8");
  if (id.length === 0 || id.length > MAX_ID_BYTES) throw new Error(`user ids are 1 to ${MAX_ID_BYTES} bytes`);
  const frame = Buffer.alloc(HEADER_SIZE + id.length + pcm.length);
  frame.writeUInt8(AUDIO_FRAME, 0);
  frame.writeBigUInt64BE(BigInt(timestampMs), 1);
  frame.writeUInt8(id.length, 9);
  id.copy(frame, HEADER_SIZE);
  pcm.copy(frame, HEADER_SIZE + id.length);
  return frame;
}

export function decodeAudioFrame(frame) {
  if (frame.length < HEADER_SIZE || frame.readUInt8(0) !== AUDIO_FRAME) throw new Error("invalid audio frame");
  const end = HEADER_SIZE + frame.readUInt8(9);
  if (end === HEADER_SIZE || frame.length < end) throw new Error("invalid audio frame");
  return {
    userId: frame.subarray(HEADER_SIZE, end).toString("utf8"),
    timestampMs: Number(frame.readBigUInt64BE(1)),
    pcm: frame.subarray(end),
  };
}

export function message(type, fields = {}) {
  return JSON.stringify({ type, ...fields });
}

export function parseMessage(text) {
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || typeof parsed.type !== "string") {
    throw new Error("invalid message");
  }
  return parsed;
}
