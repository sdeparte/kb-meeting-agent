import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { Handled, leftKey } from "../src/handled.js";

const NOW = Date.parse("2026-11-05T12:00:00Z");
const file = () => join(mkdtempSync(join(tmpdir(), "kbma-handled-")), "handled.json");

test("a marked occurrence is remembered across restarts", () => {
  const path = file();
  new Handled({ file: path, clock: () => NOW }).mark("w@x", new Date("2026-11-05T13:00:00Z"));
  assert.ok(new Handled({ file: path, clock: () => NOW }).has("w@x"));
  assert.ok(!new Handled({ file: path, clock: () => NOW }).has("other"));
  assert.doesNotThrow(() => JSON.parse(readFileSync(path, "utf8")));
});

test("occurrences ended more than a day ago are forgotten", () => {
  const path = file();
  new Handled({ file: path, clock: () => NOW }).mark("old", new Date(NOW - 25 * 3600_000));
  assert.ok(!new Handled({ file: path, clock: () => NOW }).has("old"));
});

test("a corrupt or missing file is an empty memory", () => {
  const path = file();
  assert.ok(!new Handled({ file: path, clock: () => NOW }).has("x"));
  writeFileSync(path, "{");
  const handled = new Handled({ file: path, clock: () => NOW });
  assert.ok(!handled.has("x"));
  handled.mark("x", new Date(NOW));
  assert.ok(new Handled({ file: path, clock: () => NOW }).has("x"));
});

test("a call left on purpose is remembered by its code, with the time it was left", () => {
  const path = file();
  new Handled({ file: path, clock: () => NOW }).mark(leftKey("abc-defg-hij"), new Date(NOW));
  const handled = new Handled({ file: path, clock: () => NOW });
  assert.equal(handled.leftAt("abc-defg-hij"), NOW);
  assert.equal(handled.leftAt("xyz-wxyz-xyz"), null);
});
