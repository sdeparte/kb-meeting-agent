// The huddle seen from the agent's account in the browser: accept invitations, follow who is
// speaking, turn the call's audio into per-speaker utterances, leave when asked. The UI is
// reached only through `ui` (src/ui.js), so that this logic is tested without Slack.
//
// The core says which call its meeting is in (`join`), like on Discord: the connector reports
// the voice as ready only for that call, and never records another huddle into the meeting.
export class Huddle {
  constructor({
    ui,
    page,
    makeTracker,
    agentUserId,
    channelOf, // (the meeting's channel or null) -> the joined huddle's channel, or null if unknown
    nameOf,
    commands, // kbma-browser's CommandLines: the command words come from the core's catalog
    sendToCore,
    sendAudio,
    log,
    clock = Date.now,
    missesToLeave = 30, // polls (~3 s) out of the huddle before the voice counts as lost
    membersEvery = 10, // polls between two participant reports
  }) {
    Object.assign(this, { ui, page, makeTracker, agentUserId, channelOf, nameOf, commands, sendToCore, sendAudio, log, clock });
    Object.assign(this, { missesToLeave, membersEvery });
    this.channel = null; // the huddle's channel while the agent is in it
    this.wanted = null; // the channel of the core's meeting, from its `join`
    this.tracker = null;
    this.optedOut = new Set(); // the core's meeting's opt-outs: they outlive a rejoin or a restart
    this.names = new Map(); // user id -> name shown on the huddle's tiles
    this.misses = 0;
    this.polls = 0;
    this.reported = null; // the last `members` sent
    this.askedToInvite = null;
  }

  // One invitation: wait for it, join, then start the meeting or report the voice as ready.
  async acceptInvite() {
    await this.ui.waitForInvite(this.page);
    if (this.channel) {
      this.log("ignoring a huddle invitation: already in one");
      return;
    }
    await this.ui.join(this.page);
    const channel = await this.channelOf(this.wanted);
    if (!channel) {
      this.log("left a huddle whose channel is unknown: invite the app to that channel");
      await this.ui.leave(this.page);
      return;
    }
    if (this.wanted && this.wanted !== channel) {
      this.log("left a huddle: the meeting is running in another channel");
      await this.ui.leave(this.page);
      return;
    }
    Object.assign(this, { channel, tracker: this.makeTracker(), misses: 0, polls: 0, reported: null, askedToInvite: null });
    for (const id of this.optedOut) this.tracker.optOut(id, this.clock());
    this.sendToCore("voice_state", { status: "ready" });
    await this.#reportMembers();
    if (this.wanted !== channel) this.commands.type("meeting_start", (line) => this.#chat(line, channel));
  }

  // Called every ~100 ms: who is speaking, who is there, and whether the agent is still in.
  async poll(t) {
    if (!this.channel) return;
    if (!(await this.ui.inHuddle(this.page))) {
      this.misses += 1;
      if (this.misses < this.missesToLeave) return; // the UI re-renders: not gone yet
      const channel = this.channel;
      this.#emit(this.tracker.endAll(t));
      this.channel = null;
      // Removed from the huddle, or it is over: the account cannot rejoin on its own. The core
      // records a gap and asks the participants to invite it again; with nobody left, it
      // closes the meeting after `auto_leave_empty_minutes`.
      if (this.wanted === channel) {
        this.askedToInvite = channel;
        this.sendToCore("voice_state", { status: "needs_invite" });
        this.sendToCore("members", { members: [] });
      }
      return;
    }
    this.misses = 0;
    const ids = await this.ui.speakers(this.page);
    if (ids.some((id) => !this.names.has(id))) await this.#reportMembers(); // someone new: their name first
    this.tracker.speaking(ids, new Map(ids.map((id) => [id, this.names.get(id) ?? this.nameOf(id)])), t);
    this.polls += 1;
    if (this.polls % this.membersEvery === 0) await this.#reportMembers();
  }

  onSamples(samples, t) {
    if (!this.channel || (this.wanted && this.wanted !== this.channel)) return;
    const { events, frame } = this.tracker.audio(samples, t);
    this.#emit(events);
    if (frame) this.sendAudio(frame.userId, frame.timestampMs, frame.pcm);
  }

  async onCore(msg) {
    if (msg.type === "join") {
      if (msg.voice_channel_id !== this.wanted) this.optedOut = new Set(); // another meeting
      this.wanted = msg.voice_channel_id;
      if (this.channel === this.wanted) {
        this.sendToCore("voice_state", { status: "ready" });
        this.reported = null;
        await this.#reportMembers();
      } else if (!this.channel && this.askedToInvite !== this.wanted) {
        this.askedToInvite = this.wanted; // once until the next huddle: the core repeats its join
        this.sendToCore("voice_state", { status: "needs_invite" });
      }
    } else if (msg.type === "leave") {
      [this.wanted, this.askedToInvite, this.optedOut] = [null, null, new Set()];
      if (!this.channel) return;
      this.#emit(this.tracker.endAll(this.clock()));
      this.channel = null;
      await this.ui.leave(this.page);
    } else if (msg.type === "optout") {
      this.optedOut.add(msg.user_id);
      if (this.tracker) this.#emit(this.tracker.optOut(msg.user_id, this.clock()));
    }
  }

  // The voice channel of a chat line: the huddle's, only when it is typed in its channel.
  voiceFor(channel) {
    return channel && channel === this.channel ? channel : null;
  }

  async #reportMembers() {
    const people = await this.ui.participants(this.page);
    for (const { id, name } of people) this.names.set(id, name);
    const members = people.map(({ id, name }) => ({ id, name, bot: id === this.agentUserId }));
    const key = JSON.stringify(members);
    if (key === this.reported) return;
    this.reported = key;
    this.sendToCore("members", { members });
  }

  #chat(text, channel) {
    this.sendToCore("chat", { text, user: { id: this.agentUserId, name: "Slack" }, text_channel_id: channel, voice_channel_id: channel });
  }

  #emit(events) {
    for (const e of events) this.sendToCore(e.type, { user_id: e.userId, speaker_name: e.speakerName, t: e.t });
  }
}
