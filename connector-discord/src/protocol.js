// Connector <-> core protocol, version 1. Mirrors src/kb_meeting_agent/live/protocol.py.
export const PROTOCOL_VERSION = 1;
export const AUDIO_FRAME = 0x01;
const HEADER_SIZE = 17;

export function encodeAudioFrame(userId, timestampMs, pcm) {
  const frame = Buffer.alloc(HEADER_SIZE + pcm.length);
  frame.writeUInt8(AUDIO_FRAME, 0);
  frame.writeBigUInt64BE(BigInt(userId), 1);
  frame.writeBigUInt64BE(BigInt(timestampMs), 9);
  pcm.copy(frame, HEADER_SIZE);
  return frame;
}

export function decodeAudioFrame(frame) {
  if (frame.length < HEADER_SIZE || frame.readUInt8(0) !== AUDIO_FRAME) throw new Error("invalid audio frame");
  return {
    userId: frame.readBigUInt64BE(1).toString(),
    timestampMs: Number(frame.readBigUInt64BE(9)),
    pcm: frame.subarray(HEADER_SIZE),
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
