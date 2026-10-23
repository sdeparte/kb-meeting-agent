import assert from "node:assert/strict";
import { test } from "node:test";

import { CommandLines, lineFor } from "../src/commands.js";

const catalog = [
  { id: "meeting_start", words: ["start"], slash: ["meeting", "start"] },
  { id: "meeting_end", words: ["fin", "end"], slash: ["meeting", "end"] },
];

test("a command's line is its last word from the core's catalog", () => {
  assert.equal(lineFor(catalog, "meeting_end"), "!end");
  assert.equal(lineFor(catalog, "meeting_start"), "!start");
});

test("no line without the catalog or the command", () => {
  assert.equal(lineFor(null, "meeting_end"), null);
  assert.equal(lineFor(catalog, "unknown"), null);
  assert.equal(lineFor([{ id: "meeting_end", slash: ["meeting", "end"] }], "meeting_end"), null);
});

test("a command asked for before the catalog is typed once it arrives, in order", () => {
  const commands = new CommandLines();
  const typed = [];
  commands.type("meeting_start", (line) => typed.push(["C1", line]));
  commands.type("meeting_end", (line) => typed.push(["C1", line]));
  assert.deepEqual(typed, []);
  commands.setCatalog(catalog);
  assert.deepEqual(typed, [["C1", "!start"], ["C1", "!end"]]);
  commands.type("meeting_end", (line) => typed.push(["C2", line]));
  assert.deepEqual(typed.at(-1), ["C2", "!end"]);
});
