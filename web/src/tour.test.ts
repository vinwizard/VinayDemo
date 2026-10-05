// The first-visit guide's memory and story, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeEach, test } from "node:test";
import { autoStarts, fill, INVESTIGATE_STEPS, investigateExample, loadSeen, markSeen, ONBOARD_STEPS, pickStory, readySteps, replayPart, REPORT_STEPS, resetMemory, welcomeFirst, sceneMs, STORAGE_KEY, STORY_WELCOME, termParts, type Store, type StoryRun } from "./tour.ts";

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

test("skipping the story skips the report tour it leads into, but not onboarding or the Investigate nudge", () => {
  const store = memory();
  markSeen(store, "story", "skipped");
  assert.equal(autoStarts(store, "report"), false);
  assert.equal(autoStarts(store, "onboard"), true);
  assert.equal(autoStarts(store, "investigate"), true);
});

test("skipping the welcome shown alone skips the onboard tour it hands over to, not the report tour", () => {
  const store = memory();
  markSeen(store, "story", "skipped", "onboard");
  resetMemory();   // the next load reads only what was stored
  assert.equal(autoStarts(store, "story"), false);
  assert.equal(autoStarts(store, "onboard"), false);
  assert.equal(autoStarts(store, "report"), true);
  assert.equal(welcomeFirst(store, false, true), false);
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

test("\"How it works\" always replays something, even with no report open and no story to tell", () => {
  assert.equal(replayPart(true, false), "story");
  assert.equal(replayPart(false, true), "report");
  assert.equal(replayPart(false, false), "onboard");   // the app switches to the Onboard tab first
});

test("without a story to tell, the welcome still comes first, once, and on every replay", () => {
  const s = memory();
  assert.equal(welcomeFirst(s, false, true), true);    // first visit: welcome, then the onboard tour
  markSeen(s, "story", "done");
  assert.equal(welcomeFirst(s, false, true), false);   // seen once in this browser
  assert.equal(welcomeFirst(s, false, false), true);   // "How it works" replays it
  assert.equal(welcomeFirst(memory(), true, true), false);   // with a story the welcome is its scene 0
});

const vars = { brand: "Amgen", today: 5.7, potential: 94.3, what: "what Amgen wants to be known for", example: "For example…" };
for (const [name, v, anchors] of [
  ["a live report walks Results, opens Evidence and ends on Investigate", { ...vars, live: 1 },
    ["headline", "fronts", "zones", "quick-wins", "why", "share", "evidence", "ev-tabs", "ev-downloads", "ev-tab-investigate", "ev-investigate"]],
  ["a sample run has no Investigate tab, so its tour ends on the downloads", vars,
    ["headline", "fronts", "zones", "quick-wins", "why", "share", "evidence", "ev-tabs", "ev-downloads"]],
  ["a withheld headline drops its step, never shows an empty slot", { ...vars, today: null, live: 1 },
    ["fronts", "zones", "quick-wins", "why", "share", "evidence", "ev-tabs", "ev-downloads", "ev-tab-investigate", "ev-investigate"]],
] as const) {
  test(name, () => assert.deepEqual(readySteps(REPORT_STEPS, v).map((s) => s.anchor), anchors));
}

test("each tour step that opens a page or a tab says so on its button; onboarding lights up every stage", () => {
  assert.deepEqual(REPORT_STEPS.filter((s) => s.action).map((s) => s.anchor), ["evidence", "ev-tab-investigate"]);
  assert.deepEqual(INVESTIGATE_STEPS.map((s) => s.anchor), ["evidence", "ev-tab-investigate", "ev-investigate"]);
  assert.deepEqual(ONBOARD_STEPS.map((s) => s.anchor), ["stage-1", "stage-2", "stage-3", "stage-4", "stage-5", "stage-6"]);
});

test("the Investigate example is told with the run's own Quick win, question and page", () => {
  const run = JSON.parse(readFileSync(new URL("../../data/runs/cb67186167.json", import.meta.url), "utf8")) as StoryRun;
  const text = investigateExample(run);
  assert.match(text, /“Biologic medicines made using living cells” is one of this run's Quick wins/);
  assert.match(text, /“What is Amgen, and who is it for\?”/);
  assert.match(text, /rewrite for amgen\.com\/about/);
  // nothing to tell it with: what the fleet does in general, never an invented example
  assert.doesNotMatch(investigateExample({ ...run, win_back: [] }), /For example/);
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
