// The first-visit guide: a short "how it works" story. This module holds what can be tested without
// a browser: whether the story has been seen (kept per browser) and what it shows (picked from a
// real run, never written here).
import { instant } from "./labels.ts";

/** Bump the version to show a rewritten guide again to browsers that saw the old one. */
export const STORAGE_KEY = "offmessage.tour.v1";

/** The slice of Storage the memory needs; localStorage in the page, a stub in tests. */
export interface Store { getItem(k: string): string | null; setItem(k: string, v: string): void }

// When storage throws (private window, blocked site data), memory lives for this page load only, so
// the guide still starts at most once per load instead of on every screen.
let fallback: string | null = null;

function loadSeen(store: Store | null): string | null {
  try {
    const raw = store?.getItem(STORAGE_KEY);
    return (raw ? JSON.parse(raw).story : null) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Records how the story ended, so it does not start on its own again in this browser. */
export function markSeen(store: Store | null, how: "done" | "skipped") {
  fallback = how;
  try { store?.setItem(STORAGE_KEY, JSON.stringify({ story: how })); } catch { /* kept in memory for this load */ }
}

/** Whether the story may start on its own. Replay ("How it works") never asks: it always plays. */
export const autoStarts = (store: Store | null) => !loadSeen(store);

/** Test hook: forget the in-memory fallback. */
export const resetMemory = () => { fallback = null; };

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
