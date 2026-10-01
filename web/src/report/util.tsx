import type { Answer, AttributeScore, DriftReport, Exclusion, Probe, QueryEvaluation, RetrievalRow, Run, SearchTry, VisibilitySet, Zone } from "../api";
import { ZONE_ORDER } from "../api";
import { claimShare, plain, plural } from "../labels";
import { QRef } from "./questions";

export const ZONE_FILL: Record<Zone, string> = {
  landed: "var(--landed)",
  lost_claim: "var(--win-back)",
  contested: "var(--contested)",
  unstated_intent: "var(--unstated)",
  imposed: "var(--imposed)",
  unprioritised: "var(--unprioritised)",
};

export const pct = (x: number | null) => (x == null ? 0 : Math.round(x * 100));
const endorsed = (s: AttributeScore) => Math.round((s.echo_rate ?? 0) * s.n);

/** "n/a — <why>", with the why always the server's own words. A run saved before the server
 * supplied reasons says only "n/a" rather than a guess. */
export const na = (reasons: Record<string, string> | undefined, field: string) =>
  reasons?.[field] ? `n/a — ${reasons[field]}` : "n/a";

/** How much of the site states it, or the server's reason it is not known. */
export const siteShare = (s: AttributeScore) =>
  claimShare(s.claim_pages, s.claim_pages_total, s.claim_strength) ?? na(s.na_reasons, "claim_strength");

/** How often AI raised it, or the server's reason there were no answers to count. */
export const aiShare = (s: AttributeScore) =>
  s.echo_rate == null ? na(s.na_reasons, "echo_rate")
    : `${s.echoes}/${s.n} mentioned · ${endorsed(s)} endorsed${s.negative_echoes > 0 ? ` · ${s.negative_echoes} negative` : ""}`;

/** A whole run's buyer visibility or one front's: the same fields on both. */
export type Vis = Pick<DriftReport, "visibility" | "tries" | "repeat_sample" | "visibility_range" | "low_confidence">;

/** The wobble, for the number's own popover: how much the re-asked questions moved between asks.
 * Null when nothing was asked twice, so there is nothing honest to say about it. */
export const wobbleText = (d: Vis) => (d.tries ?? 1) > 1 && d.repeat_sample && d.visibility_range
  ? `${plural(d.repeat_sample, "of these questions was", "of these questions were")} asked ${d.tries}`
    + ` times over. On their own they scored between ${d.visibility_range[0]} and`
    + ` ${d.visibility_range[1]}, so asking the very same question again moves it about that much.`
  : null;

/** The one range under the number: where it would land if the whole run were repeated. */
export const rangeText = (iv?: [number, number] | null) => !iv ? null
  : iv[0] === iv[1] ? `would stay at ${iv[0]} if we asked again` : `could be ${iv[0]}–${iv[1]} if we asked again`;

/** The same sentence for the printed summary, where nothing can be hovered. */
export const printedRange = (d: Vis, iv?: [number, number] | null) =>
  [rangeText(iv), wobbleText(d)].filter(Boolean).map((t) => ` — ${t}`).join("");

export const FRONT_TERM = { placed: "where_placed", aiming: "where_aiming" } as const;

/** The labelled fronts of a run, placed first; empty for one unlabelled set or an older run. */
export const frontsOf = (d: DriftReport): VisibilitySet[] => (d.sets ?? []).filter((v) => v.front);

/** The gap between the two fronts in one plain sentence, or why there is only one. `short` leaves out the
 * categories and numbers, for the header, where the strip and its rows already show them. */
export function gapSentence(d: DriftReport, brand: string, short = false): string | null {
  const fronts = frontsOf(d);
  const placed = fronts.find((v) => v.front === "placed"), aiming = fronts.find((v) => v.front === "aiming");
  const both = fronts.find((v) => v.front === "both");
  if (both) return `Where AI places ${brand} is the category its site aims for, ${both.category}, so one set of unbranded questions was asked.`;
  if (placed && aiming) {
    if (d.visibility_gap == null) return null;
    const flagged = placed.low_confidence || aiming.low_confidence ? " (low confidence: see Unbranded questions)" : "";
    if (short) {
      return d.visibility_gap > 0 ? `AI brings ${brand} up more where its brand answers place it than where its site aims to be.`
        : d.visibility_gap < 0 ? `AI brings ${brand} up more where its site aims to be than where its brand answers place it.`
        : `AI brings ${brand} up as often in both.`;
    }
    if (d.visibility_gap > 0) {
      return `AI already brings ${brand} up for ${placed.category} (${placed.visibility}) but less for ${aiming.category}, `
        + `where its site aims to be (${aiming.visibility}): a gap of ${d.visibility_gap} points${flagged}.`;
    }
    if (d.visibility_gap < 0) {
      return `AI brings ${brand} up more for ${aiming.category}, where its site aims to be (${aiming.visibility}), than for `
        + `${placed.category}, where its brand answers place it (${placed.visibility})${flagged}.`;
    }
    return `AI brings ${brand} up as often for ${aiming.category} as for ${placed.category} (${aiming.visibility})${flagged}.`;
  }
  if (aiming) return d.missing_fronts?.placed ?? null;
  if (placed) return d.missing_fronts?.aiming ?? null;
  return null;
}

/** The model that answered the questions and the separate one that judged them, as the answers record. */
export const modelsOf = (run: Run) => {
  const all = [run.answers, run.repeat_answers ?? []].flat();
  const list = (xs: (string | null | undefined)[]) => [...new Set(xs.filter(Boolean))].join(", ");
  return { answered: list(all.map((a) => a.model)), judged: list(all.map((a) => a.evaluator_model)) };
};

/**
 * Why an answer is left out of the scores, in words a reader can follow, or null when it counts. The
 * rule is scoring.exclusion's, applied on the server (`Answer.excluded`); this only words it.
 */
export function leftOut(a: Answer | undefined, e: QueryEvaluation | undefined, brand: string): string | null {
  if (!a || !e) return "no answer came back";
  const words: Record<Exclusion, string> = {
    missing: "no answer came back",
    snapshot: "it came from a web research snapshot, not an AI answer",
    replay: "it is a why-agent experiment on a replayed reading list, not a measurement",
    failed: "the AI call failed",
    ungrounded: "the AI answered from memory instead of searching the web",
    off_topic: `the AI answered about something other than ${brand}`,
    unconfirmed: "our checker could not confirm what the answer said",
  };
  return a.excluded ? words[a.excluded] : null;
}

/** scoring.exclusion's yes/no: only an answer that counts toward the scores can name anything here. */
export const counts = (a: Answer) => !a.excluded;

/** What a reader needs to know about one kind of question, in one sentence. */
export function questionKind(p: Probe, brand: string) {
  if (p.kind === "named") {
    return p.phase === "followup"
      ? `The comparison question: it names ${brand} beside the companies AI named instead. Exploratory — never counted in the scores.`
      : `A branded question: it names ${brand} but never a claim, so whatever AI says ${brand} is known for, it said on its own.`;
  }
  if (p.phase === "control") return "The control question: can the AI name the companies that lead this category at all? Never scored.";
  if (p.phase === "followup") return `A follow-up unbranded question: exploratory, never counted in the scores.`;
  return `An unbranded question: it never names ${brand}, so it shows whether AI brings ${brand} up on its own.`;
}

/** Several question references as "A, B and C". */
export const refs = (ids: string[], run: Run) => ids.map((id, i) => (
  <span key={id}>{i ? (i === ids.length - 1 ? " and " : ", ") : ""}<QRef id={id} run={run} /></span>
));

export const TABS = [
  ["overview", "Overview"], ["questions", "Questions we asked AI"], ["win-back", "Quick wins"],
  ["why", "Why AI misses you"], ["sources", "Sources & rivals"],
] as const;

export type ReportTab = (typeof TABS)[number][0];

export const sortClaims = (scores: AttributeScore[]) => [...scores].sort(
  (a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.mention_rate ?? b.echo_rate ?? 0) - (a.mention_rate ?? a.echo_rate ?? 0),
);

/**
 * The stretch of an answer around the first mention of a name, as plain text, so the reader can see
 * how it came up: a recommendation, a passing example, or only a citation's hostname. Falls back to
 * the raw text when stripping the Markdown removed the only mention (a name inside a link's URL).
 */
export function mention(text: string, name: string): [string, string, string] | null {
  for (const flat of [plain(text), text].map((t) => t.replace(/\s+/g, " "))) {
    const i = flat.toLowerCase().indexOf(name.toLowerCase());
    if (i < 0) continue;
    const j = i + name.length;
    const from = i > 90 ? flat.indexOf(" ", i - 90) + 1 : 0;
    const to = flat.length - j > 140 ? Math.max(j, flat.lastIndexOf(" ", j + 140)) : flat.length;
    return [(from ? "…" : "") + flat.slice(from, i), flat.slice(i, j), flat.slice(j, to) + (to < flat.length ? "…" : "")];
  }
  return null;
}

/** "A", "A and B", "A, B and C". */
export const listed = (xs: string[]) => xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`;

export type Source = NonNullable<Run["insights"]>["sources"]["sources"][number];

/** The fixtures' fictional sources (RFC 2606 hosts): never linked, since there is no page to open. */
export const placeholder = (domain: string) => /(^|\.)example\.(com|net|org)(\/|$)/.test(domain);

/** Searches as “a”, “b” and “c”. */
export const quoted = (qs: string[]) => qs.map((q, i) => (
  <span key={i}>{i ? (i === qs.length - 1 ? " and " : ", ") : ""}“{q}”</span>
));

/** Who ran the searches: the measured model through its API, by name when the answers record it. */
export const searcher = (run: Run) => modelsOf(run).answered || "the AI";

/** One try in one sentence: what the model searched, how many pages it cited, and whether any was yours. */
export function tryStory(t: SearchTry, who: string) {
  const own = t.owned_pages.length;
  return (
    <>
      {t.searches.length ? <>{who} searched {quoted(t.searches)}</> : `${who} answered without searching`}
      {t.pages.length ? ` and cited ${plural(t.pages.length, "page")}. ` : " and cited no pages."}
      {t.pages.length > 0 && (own ? <strong className="own">{own} {own === 1 ? "was" : "were"} yours.</strong> : "None was yours.")}
    </>
  );
}

export const answeredOk = (run: Run, p: Probe) =>
  [run.answers, run.repeat_answers ?? []].flat().some((a) => a.probe_id === p.id && a.status === "ok");

/** Whether any try of a question cited a page of yours; null when nothing was recorded for it. */
export const cited = (tries?: SearchTry[]) => (tries?.length ? tries.some((t) => t.owned_pages.length > 0) : null);

export const score = (x: number) => x.toFixed(2);
export const behind = (r: RetrievalRow) => !!(r.yours && r.rival && r.rival.score > r.yours.score);

/**
 * How to win it back: per claim to win back or amplify, the page to change, a suggested rewrite and
 * the buyer questions it should help with. The server kept only actions whose page was read and
 * whose questions were asked; a claim that became a target by re-scoring has no action yet.
 */
export function winBackPlan(run: Run) {
  const targets = run.attribute_scores.filter((s) => !s.discovered && (s.zone === "lost_claim" || s.zone === "unstated_intent"));
  const zones = new Set(targets.map((s) => s.attribute_id));
  return { targets, actions: (run.win_back ?? []).filter((a) => zones.has(a.attribute_id)) };
}
