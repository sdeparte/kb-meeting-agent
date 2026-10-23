// One Meet meeting seen from the agent's account in the browser: join and wait to be admitted,
// follow who speaks and who is there, pass the chat's "!" lines on, leave when asked. The UI is
// reached only through `ui` (src/ui.js), so that this logic is tested without Meet.
//
// The core says which call its meeting is in (`join`): while it has one, that call is the only
// one the agent attends, rejoined from its code if the agent dropped out or restarted, and no
// other call's audio or voice state ever reaches the core.
import { chatLine } from "./chat.js";
import { leftKey } from "./handled.js";

const CALENDAR = { id: "calendar", name: "Calendar" };
const urlOf = (code) => `https://meet.google.com/${code}`;

export class Meeting {
  constructor({
    ui,
    page,
    makeTracker,
    handled,
    commands, // kbma-browser's CommandLines: the command words come from the core's catalog
    sendToCore,
    sendAudio,
    log,
    clock = Date.now,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    admissionTimeoutMs = 600_000,
    missesToLeave = 30, // polls (~3 s) out of the call before it counts as dropped
    endsToLeave = 3, // polls out of the call with the end screen shown before it counts as over
    membersEvery = 10, // polls between two participant reports
  }) {
    Object.assign(this, { ui, page, makeTracker, handled, commands, sendToCore, sendAudio, log, clock, sleep });
    Object.assign(this, { admissionTimeoutMs, missesToLeave, endsToLeave, membersEvery });
    this.wanted = null; // the Meet code of the core's meeting, from its `join`
    this.optedOutIds = new Set(); // the core's meeting's opt-outs: they outlive a rejoin
    this.optedOutNames = new Set();
    this.rejoinFailingSince = null; // when the attempts to rejoin the wanted meeting began to throw
    this.reset();
  }

  reset() {
    this.current = null; // the occurrence being attended
    this.tracker = null;
    this.misses = 0;
    this.ends = 0;
    this.polls = 0;
    this.reported = null;
    this.seen = new Map(); // everyone seen in the tiles during this call: id -> person
  }

  // A calendar meeting. Refused while the core's meeting is in another call.
  async join(occurrence) {
    if (this.wanted && this.wanted !== occurrence.code) return false;
    const entered = await this.#enter(occurrence);
    if (entered === "not admitted") this.#markLeft(occurrence);
    return entered === "in";
  }

  // Back to the core's meeting, from its code (after a restart, or after dropping out). The
  // calendar occurrence is unknown here: leaving it on purpose is remembered by its code.
  async rejoin() {
    if (!this.wanted || this.current) return false;
    const code = this.wanted;
    const occurrence = { key: `core@${code}`, summary: "the running meeting", code, url: urlOf(code), end: new Date(this.clock()) };
    let entered;
    try {
      entered = await this.#enter(occurrence);
    } catch (error) {
      // Meet's pages may not even offer to join: give up after as long as an admission
      this.rejoinFailingSince ??= this.clock();
      if (this.clock() - this.rejoinFailingSince < this.admissionTimeoutMs) throw error;
      this.log(`could not rejoin the running meeting (${code}): ${error.message}`);
      await this.ui.abandon(this.page).catch(() => {});
      entered = "not admitted";
    }
    this.rejoinFailingSince = null;
    if (entered !== "not admitted" || this.wanted !== code) return entered === "in";
    this.#markLeft(occurrence);
    this.#command("meeting_end", code); // nobody can let the agent back in: the core closes it
    return false;
  }

  // Called every ~100 ms: is the meeting still on, who speaks, what is typed, who is there.
  async poll(t) {
    const current = this.current;
    if (!current) return;
    if (!(await this.ui.inMeeting(this.page))) {
      // The end screen, a few polls in a row: its words can also be typed in the chat
      this.ends = (await this.ui.ended(this.page)) ? this.ends + 1 : 0;
      if (this.ends >= this.endsToLeave) return this.#over(current); // ended for all, or removed
      this.misses += 1;
      if (this.misses >= this.missesToLeave) this.#dropped();
      return;
    }
    this.misses = 0;
    this.ends = 0;
    const ids = await this.ui.speakers(this.page);
    const people = await this.ui.participants(this.page);
    if (this.current !== current) return; // left meanwhile
    this.#see(people);
    this.tracker.speaking(ids, new Map([...this.seen].map(([id, p]) => [id, p.name])), t);
    const messages = await this.ui.readChat(this.page);
    if (this.current !== current || !this.#isWanted(current.code)) return;
    for (const message of messages) {
      const line = chatLine(message);
      if (line) this.#chat(line.text, this.#author(message.author), current.code);
    }
    this.polls += 1;
    if (this.polls % this.membersEvery === 0) await this.#reportMembers();
  }

  onSamples(samples, t) {
    if (!this.current || !this.#isWanted(this.current.code)) return;
    const { events, frame } = this.tracker.audio(samples, t);
    this.#emit(events);
    if (frame) this.sendAudio(frame.userId, frame.timestampMs, frame.pcm);
  }

  async onCore(msg) {
    if (msg.type === "join") {
      if (msg.voice_channel_id !== this.wanted) {
        [this.optedOutIds, this.optedOutNames] = [new Set(), new Set()];
        this.rejoinFailingSince = null;
      }
      this.wanted = msg.voice_channel_id;
      if (this.current?.code === this.wanted) {
        this.sendToCore("voice_state", { status: "ready" });
        this.reported = null;
        await this.#reportMembers();
      } else if (this.current) {
        // In another call (joined from the calendar before the core said which): back to its own
        this.log(`leaving ${this.current.summary} (${this.current.code}): the core's meeting is in another call`);
        this.#emit(this.tracker.endAll(this.clock()));
        this.reset();
        await this.ui.leave(this.page);
      }
    } else if (msg.type === "leave") {
      this.wanted = null;
      if (!this.current) return;
      this.#markLeft(this.current);
      this.#emit(this.tracker.endAll(this.clock()));
      this.reset();
      await this.ui.leave(this.page);
    } else if (msg.type === "optout") {
      this.#optOut(msg.user_id);
    }
  }

  // "in", "not admitted", or "unwanted": the core's meeting changed during the wait.
  async #enter(occurrence) {
    const rejoining = occurrence.key.startsWith("core@");
    await this.ui.open(this.page, occurrence.url);
    await this.ui.prepare(this.page);
    if ((await this.ui.askToJoin(this.page)) !== "joined" && !(await this.#admitted())) {
      this.log(`not admitted to ${occurrence.summary} (${occurrence.code})`);
      await this.ui.abandon(this.page); // no request left pending in the lobby
      return "not admitted";
    }
    // The admission can take minutes: the core may have closed its meeting, or named another
    if (rejoining ? this.wanted !== occurrence.code : !this.#isWanted(occurrence.code)) {
      this.log(`leaving ${occurrence.summary} (${occurrence.code}): no longer the core's meeting`);
      await this.ui.leave(this.page);
      return "unwanted";
    }
    const people = await this.ui.participants(this.page);
    this.reset();
    this.current = occurrence;
    this.tracker = this.makeTracker(people.find((p) => p.self)?.id ?? null);
    this.#see(people);
    this.sendToCore("voice_state", { status: "ready" });
    await this.#reportMembers();
    if (this.wanted !== occurrence.code) this.#command("meeting_start", occurrence.code);
    return "in";
  }

  async #admitted() {
    const deadline = this.clock() + this.admissionTimeoutMs;
    while (this.clock() < deadline) {
      const state = await this.ui.admitted(this.page);
      if (state === "in") return true;
      if (state === "refused") return false;
      await this.sleep(1_000);
    }
    return false;
  }

  // The meeting is over for everyone, or the agent was removed: never rejoined.
  #over(current) {
    this.#markLeft(current);
    this.#emit(this.tracker.endAll(this.clock()));
    this.#command("meeting_end", current.code);
    this.reset();
  }

  // Left on purpose: neither this occurrence nor, until it ends, any occurrence of the same
  // call (a rejoin does not know the calendar's) is joined again.
  #markLeft(occurrence) {
    this.handled.mark(occurrence.key, occurrence.end);
    this.handled.mark(leftKey(occurrence.code), new Date(this.clock()));
  }

  // Out of the call without an end screen (network, a dialog): the voice is lost, and the
  // agent goes back to the core's meeting.
  #dropped() {
    this.#emit(this.tracker.endAll(this.clock()));
    if (this.#isWanted(this.current.code)) this.sendToCore("voice_state", { status: "lost" });
    this.reset();
  }

  #isWanted(code) {
    return !this.wanted || this.wanted === code;
  }

  #see(people) {
    for (const person of people) this.seen.set(person.id, person);
    for (const person of this.seen.values()) {
      if (this.optedOutNames.has(person.name)) this.optedOutIds.add(person.id);
    }
    for (const id of this.optedOutIds) this.#emit(this.tracker?.optOut(id, this.clock()) ?? []);
  }

  // By name too: Meet gives someone who comes back a new participant id. An ambiguous name
  // opts out everyone of that name, now and later.
  #optOut(userId) {
    this.optedOutNames.add(this.seen.get(userId)?.name ?? userId);
    this.optedOutIds.add(userId);
    this.#see([]);
  }

  // The chat shows names, the audio is attributed to participant ids: a chat author is their
  // participant id when the name is unique, else the name itself, with the ids of everyone of
  // that name (`speaker_ids`), so that an opt-out reaches the audio already recorded.
  #author(name) {
    const ids = [...this.seen.values()].filter((p) => p.name === name).map((p) => p.id);
    if (ids.length === 1) return { id: ids[0], name };
    return ids.length ? { id: name, name, speaker_ids: ids } : { id: name, name };
  }

  // Everyone seen in the tiles (Meet renders only the visible ones), unless Meet counts the
  // agent alone, so that the core's auto-leave still works.
  async #reportMembers() {
    const count = await this.ui.participantCount(this.page);
    const everyone = [...this.seen.values()];
    const people = count === 1 ? everyone.filter((p) => p.self) : everyone;
    const members = people.map(({ id, name, self }) => ({ id, name, bot: Boolean(self) }));
    const key = JSON.stringify(members);
    if (key === this.reported) return;
    this.reported = key;
    this.sendToCore("members", { members });
  }

  #command(id, code) {
    this.commands.type(id, (line) => this.#chat(line, CALENDAR, code));
  }

  #chat(text, user, code) {
    this.sendToCore("chat", { text, user, text_channel_id: code, voice_channel_id: code });
  }

  #emit(events) {
    for (const e of events) this.sendToCore(e.type, { user_id: e.userId, speaker_name: e.speakerName, t: e.t });
  }
}
