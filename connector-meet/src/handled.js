// The occurrences the agent left on purpose (ended, removed, not admitted): never rejoined,
// even after a restart. A crash marks nothing, so the agent goes back and the core resumes.
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const KEPT_MS = 24 * 3600_000; // after its end, an occurrence can no longer be due

// A call (Meet code) left on purpose, marked with the time it was left: a rejoin after a drop or
// a restart does not know the calendar occurrence, so its own key would not be the one due.
export const leftKey = (code) => `left@${code}`;

export class Handled {
  constructor({ file, clock = Date.now }) {
    this.file = file;
    this.clock = clock;
    this.ends = new Map(); // occurrence key -> its end, in ms
    try {
      for (const [key, end] of Object.entries(JSON.parse(readFileSync(file, "utf8")))) {
        if (typeof end === "number") this.ends.set(key, end);
      }
    } catch {
      // missing or unreadable: start empty
    }
    this.#prune();
  }

  has(key) {
    return this.ends.has(key);
  }

  // When the call was last left on purpose, in ms, or null.
  leftAt(code) {
    return this.ends.get(leftKey(code)) ?? null;
  }

  mark(key, end) {
    this.ends.set(key, end.getTime());
    this.#prune();
    mkdirSync(dirname(this.file), { recursive: true });
    const temporary = `${this.file}.tmp`;
    writeFileSync(temporary, JSON.stringify(Object.fromEntries(this.ends)));
    renameSync(temporary, this.file);
  }

  #prune() {
    const horizon = this.clock() - KEPT_MS;
    for (const [key, end] of this.ends) if (end < horizon) this.ends.delete(key);
  }
}
