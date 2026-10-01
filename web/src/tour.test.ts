// The first-visit guide's memory and story, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";
import { autoStarts, fill, markSeen, pickStory, resetMemory, sceneMs, STORAGE_KEY, STORY_WELCOME, type Store, type StoryRun } from "./tour.ts";

const memory = (): Store & { data: Record<string, string> } => {
  const data: Record<string, string> = {};
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; } };
};
const broken: Store = {
  getItem: () => { throw new Error("SecurityError"); },
  setItem: () => { throw new Error("QuotaExceededError"); },
};

beforeEach(resetMemory);

test("the story starts on its own once per browser, then never again", () => {
  const store = memory();
  assert.equal(autoStarts(store), true);
  markSeen(store, "skipped");
  resetMemory();   // the next load reads only what was stored
  assert.equal(autoStarts(store), false);
  assert.deepEqual(JSON.parse(store.data[STORAGE_KEY]), { story: "skipped" });
});

test("blocked storage: shown at most once per page load, never an error", () => {
  assert.equal(autoStarts(broken), true);
  assert.doesNotThrow(() => markSeen(broken, "skipped"));
  assert.equal(autoStarts(broken), false);
  assert.equal(autoStarts(null), false);   // same load, no storage at all
});

test("garbage in storage reads as nothing seen", () => {
  const store = memory();
  store.data[STORAGE_KEY] = "{not json";
  assert.equal(autoStarts(store), true);
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

test("headlines fill their slots", () => {
  assert.equal(fill("{brand} at {today}%", { brand: "Amgen", today: 5.7 }), "Amgen at 5.7%");
  assert.equal(fill("{missing}", {}), "{missing}");
});

test("the story's welcome welcomes the visitor, says what the app is and credits Profound", () => {
  assert.equal(STORY_WELCOME.headline, "Hey, thank you for being here! 👋");
  assert.match(STORY_WELCOME.lead, /really excited to show you around/);
  assert.match(STORY_WELCOME.body, /how different AIs see a company/);
  assert.equal(STORY_WELCOME.creditUrl, "https://tryprofound.com");
});

test("the welcome stays up about 8 s, long enough to read; the other scenes keep 3.6 s", () => {
  assert.equal(sceneMs(0), 8000);
  for (const i of [1, 2, 3, 4]) assert.equal(sceneMs(i), 3600);
});
