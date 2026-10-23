// A browser call gives one mixed audio stream, not one per person. The platform's UI says who
// is speaking; this turns that and the audio into per-speaker utterances for the core:
// the audio goes to whoever has been speaking the longest, to `unknown` when voiced audio
// comes while nobody is shown, and an utterance ends after `silenceMs` without audio.
// While someone who opted out is shown speaking, and for `optOutGraceMs` after (the indicator
// lags), the audio is dropped: their voice is never credited to someone else. Once anyone has
// opted out, audio nobody is shown speaking (`unknown`, a held speaker) is dropped too: it may
// be the start of their speech, before the indicator shows them.
// The indicator flickers during speech: a speaker who just stopped being shown keeps the
// voiced audio for `holdMs`, unless someone else is shown.
import { floatToPcm16, rmsDbfs } from "./pcm.js";

export class SpeakerTracker {
  constructor({
    silenceMs = 600,
    voicedDbfs = -45,
    optOutGraceMs = 1000,
    holdMs = 400,
    unknown = { id: "unknown", name: "Unknown" },
    selfId = null,
  } = {}) {
    this.silenceMs = silenceMs;
    this.optOutGraceMs = optOutGraceMs;
    this.holdMs = holdMs;
    this.held = new Map(); // id that stopped being shown -> until when it keeps voiced audio
    this.optedOutShownAt = -Infinity;
    this.voicedDbfs = voicedDbfs;
    this.unknown = unknown;
    this.selfId = selfId;
    this.since = new Map(); // id shown speaking -> when it started
    this.names = new Map();
    this.optedOut = new Set();
    this.open = new Map(); // id -> time of its last attributed audio
  }

  speaking(ids, names, t) {
    for (const [id, name] of names) this.names.set(id, name);
    const shown = new Set(ids.filter((id) => id !== this.selfId));
    // Shown now, or just stopped being shown: the grace period runs from the latest of both.
    const wasShown = [...this.since.keys()].some((id) => this.optedOut.has(id));
    if (wasShown || [...shown].some((id) => this.optedOut.has(id))) this.optedOutShownAt = t;
    for (const id of this.since.keys()) {
      if (shown.has(id)) continue;
      this.since.delete(id);
      this.held.set(id, t + this.holdMs);
    }
    for (const id of shown) this.held.delete(id);
    for (const id of shown) if (!this.since.has(id)) this.since.set(id, t);
  }

  audio(samples, t) {
    const events = this.#endSilent(t);
    const speaker = this.#speaker(samples, t);
    if (speaker === null) return { events, frame: null };
    for (const id of [...this.open.keys()]) if (id !== speaker) events.push(this.#end(id, t));
    if (!this.open.has(speaker)) events.push({ type: "utterance_start", userId: speaker, speakerName: this.#name(speaker), t });
    this.open.set(speaker, t);
    return { events, frame: { userId: speaker, timestampMs: t, pcm: floatToPcm16(samples) } };
  }

  // Idempotent: a connector may repeat it (on every poll), the grace period starts once.
  optOut(id, t) {
    if (!this.optedOut.has(id)) {
      this.optedOut.add(id);
      const justShown = this.since.has(id) || (this.held.get(id) ?? -Infinity) > t;
      if (justShown || this.open.has(id)) this.optedOutShownAt = t;
    }
    return this.open.has(id) ? [this.#end(id, t)] : [];
  }

  endAll(t) {
    return [...this.open.keys()].map((id) => this.#end(id, t));
  }

  #speaker(samples, t) {
    const shown = [...this.since].sort((a, b) => a[1] - b[1]).map(([id]) => id);
    if (shown.some((id) => this.optedOut.has(id)) || t - this.optedOutShownAt < this.optOutGraceMs) return null;
    if (shown.length) return shown[0];
    if (rmsDbfs(samples) < this.voicedDbfs || this.optedOut.size) return null;
    const held = [...this.held].find(([id, until]) => until > t);
    return held ? held[0] : this.unknown.id;
  }

  #endSilent(t) {
    const ended = [];
    for (const [id, last] of [...this.open]) if (t - last >= this.silenceMs) ended.push(this.#end(id, t));
    return ended;
  }

  #end(id, t) {
    this.open.delete(id);
    return { type: "utterance_end", userId: id, speakerName: this.#name(id), t };
  }

  #name(id) {
    return id === this.unknown.id ? this.unknown.name : (this.names.get(id) ?? id);
  }
}
