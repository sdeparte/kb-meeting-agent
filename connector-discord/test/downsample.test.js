import assert from "node:assert/strict";
import { test } from "node:test";

import { downsample48kStereoTo16kMono } from "../src/downsample.js";

test("averages channels and groups of three samples", () => {
  const input = Buffer.alloc(6 * 4);
  const values = [[300, 100], [300, 100], [300, 100], [-600, 0], [-600, 0], [-600, 0]];
  values.forEach(([left, right], i) => {
    input.writeInt16LE(left, i * 4);
    input.writeInt16LE(right, i * 4 + 2);
  });
  const out = downsample48kStereoTo16kMono(input);
  assert.equal(out.length, 4);
  assert.equal(out.readInt16LE(0), 200);
  assert.equal(out.readInt16LE(2), -300);
});

test("a 20 ms Opus frame becomes 320 samples", () => {
  assert.equal(downsample48kStereoTo16kMono(Buffer.alloc(960 * 4)).length, 640);
});
