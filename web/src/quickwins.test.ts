// Quick wins and claims-step arithmetic, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { test } from "node:test";
import { checkProblems, intentWord, matchRows, matchVerdict, missedQuestions, wordDiff, wordsIn } from "./quickwins.ts";

test("the diff shows what a rewrite keeps, removes and adds, word by word", () => {
  // Amgen, 28 Sep 2026: the biologics rewrite kept most of the sentence already on amgen.com/about.
  const parts = wordDiff("Many of Amgen's medicines are made through a highly complex process involving living cells.",
    "Amgen develops biologic medicines using living cells. Many of Amgen’s medicines are made through this highly complex process.");
  assert.deepEqual(parts.slice(0, 2).map((p) => p.op), ["add", "same"]);
  assert.equal(parts[0].text, "Amgen develops biologic medicines using living cells.");
  assert.ok(parts.some((p) => p.op === "del" && p.text === "a"));
  assert.ok(parts.some((p) => p.op === "same" && p.text.includes("Amgen’s medicines")));   // curly quote is the same word
  assert.equal(wordsIn(parts, "add"), 8);
  assert.equal(wordsIn(parts, "del"), 4);
  assert.deepEqual(wordDiff("", "New passage."), [{ op: "add", text: "New passage." }]);
});

const row = (probe_id: string, yours: number | null, rival: number | null, fixed: number | null, fix = "bio") => ({
  probe_id, fix_attribute_id: fixed == null ? null : fix,
  yours: yours == null ? null : { url: "u", text: "t", score: yours, query: "q" },
  rival: rival == null ? null : { url: "r", text: "t", score: rival, query: "q" },
  fixed: fixed == null ? null : { url: "u", text: "t", score: fixed, query: "q" },
});
const action = (question_ids: string[]) => ({ attribute_id: "bio", question_ids });

test("match rows put today, the page AI cited and the rewrite side by side", () => {
  // Amgen, 28 Sep 2026: worse on 2 of 3 (0.56 -> 0.53, 0.45 -> 0.47, 0.50 -> 0.47)
  const rows = matchRows(action(["b1", "b2", "b3", "b4"]),
    [row("b1", 0.56, 0.7, 0.53), row("b2", 0.45, null, 0.47), row("b3", 0.5, 0.75, 0.47), row("b4", 0.4, null, 0.6, "other")]);
  assert.deepEqual(rows.map((r) => [r.today, r.cited, r.fixed, r.change]),
    [[0.56, 0.7, 0.53, -0.03], [0.45, null, 0.47, 0.02], [0.5, 0.75, 0.47, -0.03], [0.4, null, null, null]]);
  assert.deepEqual(matchVerdict(rows), { verdict: "worse", closer: 1, worse: 2, scored: 3 });
});

test("a move inside the wobble is no change, and nothing scored is said so", () => {
  // Amgen innovation, 28 Sep 2026: 0.56 -> 0.57
  assert.equal(matchVerdict(matchRows(action(["b"]), [row("b", 0.56, null, 0.57)])).verdict, "no_change");
  assert.equal(matchVerdict(matchRows(action(["b"]), [row("b", 0.4, 0.6, 0.55)])).verdict, "closer");
  assert.equal(matchVerdict(matchRows(action(["b"]), [])).verdict, "not_scored");
});

test("an intent weight reads as words over the same 0–1 value", () => {
  assert.deepEqual([0, 0.1, 0.4, 0.5, 0.8, 0.9, 1].map(intentWord),
    ["Not a goal", "Nice to have", "Nice to have", "Important", "Important", "Top priority", "Top priority"]);
});

test("a buyer question is missed when no try cited one of your pages", () => {
  const t = (owned: string[]) => ({ try_no: 1, searches: ["s"], pages: ["p"], owned_pages: owned });
  assert.deepEqual(missedQuestions({ a: [t([]), t(["x"])], b: [t([]), t([])], c: [] }, ["a", "b", "c", "d"]), ["b"]);
});

test("what is in AI's way is counted once across the claim pages, most first", () => {
  // Amgen, 28 Sep 2026: the same five pills and the same advice, repeated for all 7 claims.
  const page = (speed: string) => ({ checks: [{ key: "crawlers", status: "pass" }, { key: "markup", status: "fail" }, { key: "speed", status: speed }] });
  const got = checkProblems([page("pass"), page("fail"), page("fail")]);
  assert.deepEqual(got.failing, [{ key: "markup", n: 3 }, { key: "speed", n: 2 }]);
  assert.deepEqual(got.passing, ["crawlers"]);
  assert.equal(got.pages, 3);
});
