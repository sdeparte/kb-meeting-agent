// Utterance boundaries per speaker: an utterance ends after a real silence (Discord's own
// "speaking end" fires at every short pause) and is capped at Whisper's 30 s window.
export const MAX_UTTERANCE_MS = 30_000;
export const SILENCE_MS = 800;
const PACKET_MS = 20;

export class UtteranceTracker {
  constructor({ maxMs = MAX_UTTERANCE_MS, silenceMs = SILENCE_MS } = {}) {
    this.maxMs = maxMs;
    this.silenceMs = silenceMs;
    this.open = new Map(); // userId -> { startedAt, lastAt }
  }

  start(userId, now) {
    if (this.open.has(userId)) return [];
    this.open.set(userId, { startedAt: now, lastAt: now });
    return [{ type: "utterance_start", t: now }];
  }

  packet(userId, now) {
    const current = this.open.get(userId);
    if (current === undefined) return this.start(userId, now);
    if (now - current.startedAt < this.maxMs) {
      current.lastAt = now;
      return [];
    }
    this.open.set(userId, { startedAt: now, lastAt: now });
    return [
      { type: "utterance_end", t: now },
      { type: "utterance_start", t: now },
    ];
  }

  end(userId, now) {
    if (!this.open.delete(userId)) return [];
    return [{ type: "utterance_end", t: now }];
  }

  // Close the utterances whose speaker has been silent for silenceMs; call it periodically.
  endSilent(now) {
    const events = [];
    for (const [userId, { lastAt }] of this.open) {
      if (now - lastAt >= this.silenceMs) {
        this.open.delete(userId);
        events.push({ userId, type: "utterance_end", t: lastAt + PACKET_MS });
      }
    }
    return events;
  }

  endAll(now) {
    const events = [...this.open.keys()].map((userId) => ({ userId, type: "utterance_end", t: now }));
    this.open.clear();
    return events;
  }
}
