// Utterance boundaries per speaker, capped at Whisper's 30 s window.
export const MAX_UTTERANCE_MS = 30_000;

export class UtteranceTracker {
  constructor({ maxMs = MAX_UTTERANCE_MS } = {}) {
    this.maxMs = maxMs;
    this.open = new Map();
  }

  start(userId, now) {
    if (this.open.has(userId)) return [];
    this.open.set(userId, now);
    return [{ type: "utterance_start", t: now }];
  }

  packet(userId, now) {
    const startedAt = this.open.get(userId);
    if (startedAt === undefined) return this.start(userId, now);
    if (now - startedAt < this.maxMs) return [];
    this.open.set(userId, now);
    return [
      { type: "utterance_end", t: now },
      { type: "utterance_start", t: now },
    ];
  }

  end(userId, now) {
    if (!this.open.delete(userId)) return [];
    return [{ type: "utterance_end", t: now }];
  }

  endAll(now) {
    const events = [...this.open.keys()].map((userId) => ({ userId, type: "utterance_end", t: now }));
    this.open.clear();
    return events;
  }
}
