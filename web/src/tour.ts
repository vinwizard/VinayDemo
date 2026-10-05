// The first-visit guide: a short "how it works" story, then a spotlight tour of the screen. This
// module holds what can be tested without a browser: which parts have been seen (kept per browser),
// what the story shows (picked from a real run, never written here), and the tour's copy.
import { instant } from "./time.ts";

/**
 * The parts that can start on their own, once per browser: the story, the onboarding tour, the
 * report tour (Results, then Evidence), and the nudge to Investigate after a result is generated.
 */
export type Part = "story" | "report" | "onboard" | "investigate";
export type Seen = Partial<Record<Part, "done" | "skipped">>;

/** Bump the version to show a rewritten guide again to browsers that saw the old one. */
export const STORAGE_KEY = "offmessage.tour.v1";

/** The slice of Storage the memory needs; localStorage in the page, a stub in tests. */
export interface Store { getItem(k: string): string | null; setItem(k: string, v: string): void }

// When storage throws (private window, blocked site data), memory lives for this page load only, so
// the guide still starts at most once per load instead of on every screen.
let fallback: Seen = {};

export function loadSeen(store: Store | null): Seen {
  try {
    const raw = store?.getItem(STORAGE_KEY);
    return raw ? { ...fallback, ...JSON.parse(raw) } : { ...fallback };
  } catch {
    return { ...fallback };
  }
}

/**
 * Records how a part ended. Skipping the story skips the tour it leads into as well (`then`: the
 * report tour, or for a welcome shown alone the tour it hands over to): a visitor who said "no
 * guide" is not guided again on the next screen.
 */
export function markSeen(store: Store | null, part: Part, how: "done" | "skipped", then: "report" | "onboard" = "report"): Seen {
  const seen: Seen = { ...loadSeen(store), [part]: how };
  if (part === "story" && how === "skipped") seen[then] ??= "skipped";
  fallback = seen;
  try { store?.setItem(STORAGE_KEY, JSON.stringify(seen)); } catch { /* kept in memory for this load */ }
  return seen;
}

/** Whether a part may start on its own. Replay ("How it works") never asks: it always plays. */
export const autoStarts = (store: Store | null, part: Part) => !loadSeen(store)[part];

/** Test hook: forget the in-memory fallback. */
export const resetMemory = () => { fallback = {}; };

// ------------------------------------------------------------------------------------------ story

/**
 * The fields of a run the story reads (api.Run has them and more). Declared here so this module
 * stays free of the browser-only API client and runs under `node --test`.
 */
export interface StoryRun {
  mode: string;
  created_at: string;
  profile: { name: string; domain: string };
  drift: { imposed: string[] } | null;
  probes: { id: string; text: string; kind: string; phase?: string }[];
  answers: { probe_id: string; text: string; model: string | null; collected_at: string | null }[];
  attributes?: { id: string; claim_quotes: string[]; intended_weight: number | null; discovered?: boolean }[];
  attribute_scores: { attribute_id?: string; label: string; zone: string; quotes: string[]; probe_ids: string[]; negative_rate: number | null; discovered?: boolean }[];
  win_back?: { attribute_id: string; page_url: string; current_copy: string | null; rewrite: string }[];
}

export interface Story {
  brand: string;
  domain: string;
  /** Scene 1: a sentence from the company's own site, as the claim stores it. */
  claim: string;
  /** Scene 2: a branded question and short pieces of its answer, in answer order, as the answer spells them. */
  question: string;
  pieces: string[];
  /** Which piece is the identity AI gave the brand (shown in bold), or -1. */
  identityPiece: number;
  /** Scene 3: a trait AI gives the brand that the brand never claimed. */
  identity: string | null;
  /** Scene 4: the first Quick wins fix. */
  fixPage: string;
  fixBefore: string | null;
  fixAfter: string;
  /** When the answers were collected, e.g. "Sep 28, 2026", and by which model. */
  collected: string | null;
  model: string | null;
}

// Evaluation matches a quote in its answer ignoring markdown emphasis and case (README), so the
// story finds it the same way and then shows the answer's own words, not the stored quote.
const plain = (s: string) => s.replace(/\*\*|__|\*/g, "");

function locate(answer: string, quote: string): { at: number; text: string } | null {
  const body = plain(answer);
  const at = body.toLowerCase().indexOf(plain(quote).toLowerCase().trim());
  return at < 0 ? null : { at, text: body.slice(at, at + plain(quote).trim().length) };
}

const day = (iso: string | null | undefined) => {
  if (!iso) return null;
  const d = instant(iso);
  return Number.isNaN(d.getTime()) ? null
    : d.toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};

/**
 * Everything the story shows, taken from one measured run, or null when the run cannot tell the
 * whole story (not measured live, no fix, no quotable answer). Nothing is invented to fill a gap.
 */
export function pickStory(run: StoryRun): Story | null {
  if (run.mode !== "live_api" || !run.drift) return null;
  const fix = run.win_back?.[0];
  if (!fix) return null;
  const attrs = run.attributes ?? [];
  const claimed = attrs.find((a) => a.id === fix.attribute_id && a.claim_quotes.length)
    ?? attrs.filter((a) => !a.discovered && a.claim_quotes.length)
      .sort((a, b) => (b.intended_weight ?? 0) - (a.intended_weight ?? 0))[0];
  if (!claimed) return null;

  // Scene 2 and 3 share one answer: the one where AI gave the brand a trait it never claimed,
  // a critical one first, since that is the gap a newcomer grasps fastest.
  const imposed = run.attribute_scores
    .filter((s) => s.zone === "imposed" && s.quotes.length)
    .sort((a, b) => (b.negative_rate ?? 0) - (a.negative_rate ?? 0));
  for (const identity of imposed) {
    for (const pid of identity.probe_ids) {
      const probe = run.probes.find((p) => p.id === pid && p.kind === "named");
      const answer = run.answers.find((a) => a.probe_id === pid);
      if (!probe || !answer) continue;
      const mine = identity.quotes.map((q) => locate(answer.text, q)).find(Boolean);
      if (!mine) continue;
      const others = run.attribute_scores
        .filter((s) => s !== identity)
        .flatMap((s) => s.quotes.map((q) => locate(answer.text, q)))
        .filter((x): x is { at: number; text: string } => !!x && x.at !== mine.at)
        .slice(0, 2);
      const pieces = [mine, ...others].sort((a, b) => a.at - b.at);
      return {
        brand: run.profile.name,
        domain: run.profile.domain,
        claim: claimed.claim_quotes[0],
        question: probe.text,
        pieces: pieces.map((p) => p.text),
        identityPiece: pieces.indexOf(mine),
        identity: identity.label,
        fixPage: fix.page_url,
        fixBefore: fix.current_copy,
        fixAfter: fix.rewrite,
        collected: day(answer.collected_at ?? run.created_at),
        model: answer.model,
      };
    }
  }
  return null;
}

// ------------------------------------------------------------------------------------------- copy

/** The scene before the story: what the app is, before it is shown on a real run. */
export const STORY_WELCOME = {
  headline: "Hey, thank you for being here! 👋",
  lead: "Welcome to my portfolio demo - I'm really excited to show you around.",
  body: "It's my take on an AI marketer's first step: finding out how different AIs see a company, and whether that matches what the company wants to be known for.",
  /** Rendered "Inspired by <a>Profound</a>." */
  creditUrl: "https://tryprofound.com",
};

/** How long each story scene shows: the welcome has more to read than a scene's one line. */
export const sceneMs = (scene: number) => scene === 0 ? 8000 : 3600;

export const STORY_HEADLINES = [
  "{brand}'s website says who {brand} is.",
  "Then we ask AI what it thinks of {brand}.",
  "Then we measure the gap.",
  "And we show what to change.",
];

/** Fills {name} slots; an unknown slot stays visible rather than silently vanishing. */
export const fill = (s: string, vars: Record<string, string | number | null | undefined>) =>
  s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] == null ? m : String(vars[k])));

// ------------------------------------------------------------------------------------------- tour

/**
 * A tour step: the element it lights up (its data-tour value), a short title and one sentence.
 * `action` names the button that clicks the element and moves on (to the page or tab it opens);
 * `live` steps are left out of a run that was not measured live.
 */
export interface Step { anchor: string; title: string; text: string; action?: string; live?: boolean }

// The Results captions are the ones the captain approved on the design board (28 Sep 2026). Terms
// the product invented are marked [[key|words]] and render as the glossary's own hover definition.
const EVIDENCE: Step = { anchor: "evidence", title: "The evidence",
  text: "Everything behind these numbers: every question we asked AI, its full answer, and how we checked.",
  action: "Open the evidence" };
const INVESTIGATE: Step[] = [
  { anchor: "ev-tab-investigate", title: "Dig deeper", live: true, action: "Show me",
    text: "The numbers say what AI says. [[investigation_fleet|Investigate the gaps]], on its own tab, works out why, and what would change it." },
  { anchor: "ev-investigate", title: "Investigate the gaps", live: true,
    text: "{example} The button shows what it costs before you start, and nothing it finds moves a score." },
];

export const REPORT_STEPS: Step[] = [
  { anchor: "headline", title: "The gap",
    text: "AI repeats {today}% of {what}. The other {potential}% is [[untapped_potential|untapped potential]]." },
  { anchor: "fronts", title: "Does AI bring you up?",
    text: "When a buyer asks AI for this kind of company without naming {brand}, does AI bring {brand} up? This is [[buyer_visibility|buyer visibility]], out of 100." },
  { anchor: "zones", title: "Claims, sorted",
    text: "Each claim lands in one group, by what AI does with it. Hover a group to see its claims and AI's own words." },
  { anchor: "quick-wins", title: "What to do first",
    text: "Start here to act: [[quick_wins|Quick wins]] names the page to change and a suggested rewrite for each claim." },
  { anchor: "why", title: "Why AI misses you",
    text: "Three numbers on why AI passes {brand} over: what it searched, how well {brand}'s pages match the question, and what the site check found. Each opens its table in the evidence." },
  { anchor: "share", title: "Who AI recommends",
    text: "When buyers ask, how often AI recommends {brand}, next to the companies it names instead: [[share_of_voice|share of voice]]." },
  EVIDENCE,
  { anchor: "ev-tabs", title: "One part at a time",
    text: "Each part of the evidence has its own tab, and only that part shows: what we asked AI, what it searched, fixes and tests, the site check, cited sites, and how we checked." },
  { anchor: "ev-downloads", title: "Take it with you",
    text: "Download a one-page summary as a PDF, or the whole run as data." },
  ...INVESTIGATE,
];

/** After a live result is generated: from its results straight to Investigate, with a worked example. */
export const INVESTIGATE_STEPS: Step[] = [
  { ...EVIDENCE, title: "Your result is in",
    text: "Next, find out why AI says what it says. It starts in the evidence." },
  ...INVESTIGATE,
];

export const ONBOARD_STEPS: Step[] = [
  { anchor: "stage-1", title: "Start with a name",
    text: "Type a company's name. We find its website, you confirm it, and we read its own pages (or documents you upload)." },
  { anchor: "stage-2", title: "Only what they say",
    text: "An AI pulls out what those pages claim, and keeps a claim only if it can quote it word for word." },
  { anchor: "stage-3", title: "Your priorities",
    text: "Optional: mark what you want to be known for. Skip it and we measure what the site already says." },
  { anchor: "stage-4", title: "What AI says about you",
    text: "[[brand_question|Branded questions]] name the company but never a claim, so whatever AI says it is known for, it said unprompted." },
  { anchor: "stage-5", title: "Does AI bring you up?",
    text: "[[buyer_question|Unbranded questions]] are what a buyer would type without naming the company. Does AI bring it up on its own?" },
  { anchor: "stage-6", title: "Then we score",
    text: "Every quote is checked word for word against its answer, then each claim is placed. Your report opens right here." },
];

/** What "How it works" replays: the story when it can be told, else the tour of the screen it opens on. */
export const replayPart = (hasStory: boolean, reportOpen: boolean): Part =>
  hasStory ? "story" : reportOpen ? "report" : "onboard";

/**
 * Without a story to tell (the showcase run could not be read), the welcome scene still opens the
 * guide: on a first visit before the tour that would auto-start, and on every replay.
 */
export const welcomeFirst = (store: Store | null, hasStory: boolean, auto: boolean) =>
  !hasStory && (!auto || autoStarts(store, "story"));

/** What the headline measures, as the report reads it: intent once weighted, else the site's claims. */
export const measuredWhat = (brand: string, lens: string | null | undefined) =>
  lens === "claim" ? `what ${brand}'s site claims` : `what ${brand} wants to be known for`;

/** The steps a report can show: none with an empty slot (a number it withheld), live ones only when live. */
export const readySteps = (steps: Step[], vars: Record<string, string | number | null | undefined>) =>
  steps.filter((s) => (!s.live || !!vars.live) && !/\{\w+\}/.test(fill(s.text, vars)));

/** Splits a caption into plain text and [[glossary|words]] parts. */
export function termParts(s: string): ({ text: string } | { term: string; text: string })[] {
  return s.split(/(\[\[\w+\|[^\]]+\]\])/).filter(Boolean).map((p) => {
    const m = /^\[\[(\w+)\|([^\]]+)\]\]$/.exec(p);
    return m ? { term: m[1], text: m[2] } : { text: p };
  });
}

/**
 * What an investigation does, told on this run: its first Quick win, a branded question it asked and
 * the page the fix rewrites. Without all three it says what the fleet does in general.
 */
export function investigateExample(run: StoryRun): string {
  const targets = run.attribute_scores.filter((s) => !s.discovered && (s.zone === "lost_claim" || s.zone === "unstated_intent"));
  const fix = run.win_back?.find((w) => targets.some((s) => s.attribute_id === w.attribute_id));
  const claim = targets.find((s) => s.attribute_id === fix?.attribute_id);
  const question = run.probes.find((p) => p.kind === "named" && (p.phase ?? "baseline") === "baseline");
  if (!fix || !claim || !question) {
    return "A coordinator picks the claims AI misses, investigators test what would make AI say them, "
      + "and the fixes that worked come back as a ranked plan.";
  }
  const page = fix.page_url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
  return `For example, “${claim.label}” is one of this run's Quick wins. An investigator asks AI “${question.text}”, `
    + `records what it read, then hands it the same reading with the rewrite for ${page} put in, and asks again `
    + "many times to see whether the claim comes through.";
}
