// Report tab badges, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { test } from "node:test";
import { tabBadge } from "./badge.ts";

test("a tab badge says what it counts, and is never a bare 0", () => {
  // Amgen, 22 Sep 2026: the tab read "Win it back 0", and a first-time reader took it for a score.
  assert.equal(tabBadge(2, "claim", "✓"), "2 claims");
  assert.equal(tabBadge(1, "question"), "1 question");
  assert.equal(tabBadge(0, "claim", "✓"), "✓");       // nothing left to fix is good news
  assert.equal(tabBadge(0, "site"), undefined);        // nothing to list shows no badge at all
  assert.equal(tabBadge(undefined, "claim", "✓"), undefined);
});
