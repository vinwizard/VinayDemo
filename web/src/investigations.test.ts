// The why view's grouping, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { test } from "node:test";
import { latestPerClaim } from "./investigations.ts";

const inv = (id: string, attribute_id: string, question: string, created_at: string) =>
  ({ id, attribute_id, question, created_at });

test("one card per claim and question, newest first, older ones behind it", () => {
  // Amgen, 28 Sep 2026: two "Uses AI…" and two "Debt…" cards with different verdicts, side by side.
  const got = latestPerClaim([
    inv("debt-1", "debt", "What are Amgen's main strengths and weaknesses?", "2026-09-28T03:52:16"),
    inv("ai-1", "ai", "What makes Amgen different?", "2026-09-28T03:59:16"),
    inv("ai-2", "ai", "What makes Amgen different? ", "2026-09-28T04:06:22"),
    inv("debt-2", "debt", "What are Amgen's main strengths and weaknesses?", "2026-09-28T04:06:20"),
    inv("ai-other", "ai", "What is Amgen best known for?", "2026-09-28T04:10:00"),
  ]);
  assert.deepEqual(got.map((g) => [g.latest.id, g.earlier.map((e) => e.id)]),
    [["ai-other", []], ["ai-2", ["ai-1"]], ["debt-2", ["debt-1"]]]);
});

test("nothing to group is nothing to show", () => {
  assert.deepEqual(latestPerClaim([]), []);
});
