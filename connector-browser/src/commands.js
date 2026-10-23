// The meeting commands a browser connector types on its own (`!start` when invited into a
// call, `!fin` when it is over), from the catalog the core sends in its `commands` message:
// the core alone defines the command words (src/kb_meeting_agent/commands.py).

// The "!" line of a command, or null when the catalog does not have it.
export function lineFor(catalog, id) {
  const words = catalog?.find((command) => command.id === id)?.words;
  return words?.length ? `!${words.at(-1)}` : null;
}

// A command asked for before the catalog has arrived (the connector joined a call before the
// core's link was up) is typed once it does.
export class CommandLines {
  constructor() {
    this.catalog = null;
    this.pending = [];
  }

  // The core's `commands` message.
  setCatalog(catalog) {
    this.catalog = catalog;
    const pending = this.pending;
    this.pending = [];
    for (const [id, type] of pending) this.type(id, type);
  }

  // Calls `type` with the command's "!" line, now or once the catalog has arrived.
  type(id, type) {
    if (!this.catalog) {
      this.pending.push([id, type]);
      return;
    }
    const line = lineFor(this.catalog, id);
    if (line) type(line);
  }
}
