// The first-visit guide's memory and story, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";
import { autoStarts, fill, loadSeen, markSeen, pickStory, replayPart, resetMemory, STORAGE_KEY, termParts, type Store, type StoryRun } from "./tour.ts";

const memory = (): Store & { data: Record<string, string> } => {
  const data: Record<string, string> = {};
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; } };
};
const broken: Store = {
  getItem: () => { throw new Error("SecurityError"); },
  setItem: () => { throw new Error("QuotaExceededError"); },
};

beforeEach(resetMemory);

test("each part starts on its own once per browser, then never again", () => {
  const store = memory();
  assert.equal(autoStarts(store, "story"), true);
  markSeen(store, "story", "done");
  assert.equal(autoStarts(store, "story"), false);
  assert.equal(autoStarts(store, "report"), true);   // finishing the story still leads into the tour
  assert.deepEqual(JSON.parse(store.data[STORAGE_KEY]), { story: "done" });
});

test("skipping the story skips the report tour it leads into, but not onboarding", () => {
  const store = memory();
  markSeen(store, "story", "skipped");
  assert.equal(autoStarts(store, "report"), false);
  assert.equal(autoStarts(store, "onboard"), true);
});

test("a report tour already finished is not downgraded to skipped", () => {
  const store = memory();
  markSeen(store, "report", "done");
  markSeen(store, "story", "skipped");
  assert.equal(loadSeen(store).report, "done");
});

test("blocked storage: shown at most once per page load, never an error", () => {
  assert.equal(autoStarts(broken, "report"), true);
  assert.doesNotThrow(() => markSeen(broken, "report", "skipped"));
  assert.equal(autoStarts(broken, "report"), false);
  assert.equal(autoStarts(null, "report"), false);   // same load, no storage at all
});

test("garbage in storage reads as nothing seen", () => {
  const store = memory();
  store.data[STORAGE_KEY] = "{not json";
  assert.equal(autoStarts(store, "story"), true);
});

test("the story is the showcase run's own words, verbatim in their sources", () => {
  // The committed Amgen live run (28 Sep 2026) that the public demo opens on.
  const run = JSON.parse(readFileSync(new URL("../../data/runs/cb67186167.json", import.meta.url), "utf8")) as StoryRun;
  const s = pickStory(run);
  assert.ok(s);
  const claim = run.attributes!.find((a) => a.claim_quotes.includes(s.claim));
  assert.ok(claim, "scene 1 quotes a claim the run stores");
  const probe = run.probes.find((p) => p.text === s.question)!;
  assert.equal(probe.kind, "named");
  const answer = run.answers.find((a) => a.probe_id === probe.id)!.text.replace(/\*\*|__|\*/g, "");
  let last = -1;
  for (const piece of s.pieces) {
    const at = answer.indexOf(piece);
    assert.ok(at > last, `"${piece}" is in the answer, in order`);
    last = at;
  }
  assert.ok(s.identity && run.drift!.imposed.includes(s.identity), "scene 3 is an identity AI gave, not a claim");
  assert.ok(s.identityPiece >= 0);
  assert.deepEqual([s.fixBefore, s.fixAfter], [run.win_back![0].current_copy, run.win_back![0].rewrite]);
  assert.equal(s.collected, "Sep 28, 2026");
});

test("a replayed sample never feeds the story", () => {
  const run = JSON.parse(readFileSync(new URL("../../data/runs/cb67186167.json", import.meta.url), "utf8")) as StoryRun;
  assert.equal(pickStory({ ...run, mode: "demo" }), null);
  assert.equal(pickStory({ ...run, win_back: [] }), null);
});

test("captions fill their slots and keep glossary terms apart", () => {
  assert.equal(fill("{brand} at {today}%", { brand: "Amgen", today: 5.7 }), "Amgen at 5.7%");
  assert.equal(fill("{missing}", {}), "{missing}");
  assert.deepEqual(termParts("The other 9% is [[untapped_potential|untapped potential]]."), [
    { text: "The other 9% is " }, { term: "untapped_potential", text: "untapped potential" }, { text: "." },
  ]);
});

test("\"How it works\" always replays something, even for a pass holder on History with no report open", () => {
  assert.equal(replayPart(true, false), "story");
  assert.equal(replayPart(false, true), "report");
  assert.equal(replayPart(false, false), "onboard");   // the app switches to the Onboard tab first
});
