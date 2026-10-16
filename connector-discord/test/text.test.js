import assert from "node:assert/strict";
import { test } from "node:test";

import { DISCORD_MESSAGE_LIMIT, truncate } from "../src/text.js";

test("truncate keeps messages within Discord's limit", () => {
  assert.equal(truncate("short"), "short");
  const long = truncate("x".repeat(5000));
  assert.equal(long.length, DISCORD_MESSAGE_LIMIT);
  assert.ok(long.endsWith("…"));
});
