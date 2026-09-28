// The first-visit guide: a short "how it works" story, then a spotlight tour of the screen. This
// module holds what can be tested without a browser: which parts have been seen (kept per browser),
// what the story shows (picked from a real run, never written here), and the tour's copy.

/** The three parts that can start on their own, once per browser. */
export type Part = "story" | "report" | "onboard";
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
 * Records how a part ended. Skipping the story skips the report tour it leads into as well: a visitor
 * who said "no guide" is not guided again on the next screen.
 */
export function markSeen(store: Store | null, part: Part, how: "done" | "skipped"): Seen {
  const seen: Seen = { ...loadSeen(store), [part]: how };
  if (part === "story" && how === "skipped") seen.report ??= "skipped";
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
  probes: { id: string; text: string; kind: string }[];
  answers: { probe_id: string; text: string; model: string | null; collected_at: string | null }[];
  attributes?: { id: string; claim_quotes: string[]; intended_weight: number | null; discovered?: boolean }[];
  attribute_scores: { label: string; zone: string; quotes: string[]; probe_ids: string[]; negative_rate: number | null }[];
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
  const d = new Date(iso);
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

/** A tour step: the element it lights up (its data-tour value), a short title and one sentence. */
export interface Step { anchor: string; title: string; text: string; action?: string }

// Captions as the captain approved them on the design board (28 Sep 2026). Terms the product
// invented are marked [[key|words]] and render as the glossary's own hover definition.
export const REPORT_STEPS: Step[] = [
  { anchor: "headline", title: "The gap",
    text: "AI repeats {today}% of {what}. The other {potential}% is [[untapped_potential|untapped potential]]." },
  { anchor: "fronts", title: "Does AI bring you up?",
    text: "When a buyer asks AI for this kind of company without naming {brand}, does AI bring {brand} up? This is [[buyer_visibility|buyer visibility]], out of 100." },
  { anchor: "zones", title: "Claims, sorted",
    text: "Each claim lands in one group, by what AI does with it. Hover a group to see its claims and AI's own words." },
  { anchor: "tab-questions", title: "The evidence",
    text: "Every question we asked AI, with its full answer. [[brand_question|Branded]] and [[buyer_question|unbranded]] questions sit side by side." },
  { anchor: "tab-win-back", title: "What to do",
    text: "Start here to act: the page to change, and a suggested rewrite for each claim.", action: "Open Quick wins" },
];

export const ONBOARD_STEPS: Step[] = [
  { anchor: "onboard-form", title: "Start with a website",
    text: "Give a company name and its website. We read its own pages and keep only claims we can quote word for word." },
  { anchor: "onboard-intent", title: "Your priorities",
    text: "Optional: mark what you want to be known for. Skip it and we measure what the site already says." },
  { anchor: "onboard-measure", title: "Then we measure",
    text: "Then we ask AI and score the answers. A run costs about $0.85 of your pass at the default settings." },
];

export const STORY_HEADLINES = [
  "{brand}'s website says who {brand} is.",
  "Then we ask AI what it thinks of {brand}.",
  "Then we measure the gap.",
  "And we show what to change.",
];

/** What the headline measures, as the report reads it: intent once weighted, else the site's claims. */
export const measuredWhat = (brand: string, lens: string | null | undefined) =>
  lens === "claim" ? `what ${brand}'s site claims` : `what ${brand} wants to be known for`;

/** A step whose caption still has an empty slot (a number the report withheld) is left out. */
export const readySteps = (steps: Step[], vars: Record<string, string | number | null | undefined>) =>
  steps.filter((s) => !/\{\w+\}/.test(fill(s.text, vars)));

/** Fills {name} slots; an unknown slot stays visible rather than silently vanishing. */
export const fill = (s: string, vars: Record<string, string | number | null | undefined>) =>
  s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] == null ? m : String(vars[k])));

/** Splits a caption into plain text and [[glossary|words]] parts. */
export function termParts(s: string): ({ text: string } | { term: string; text: string })[] {
  return s.split(/(\[\[\w+\|[^\]]+\]\])/).filter(Boolean).map((p) => {
    const m = /^\[\[(\w+)\|([^\]]+)\]\]$/.exec(p);
    return m ? { term: m[1], text: m[2] } : { text: p };
  });
}
