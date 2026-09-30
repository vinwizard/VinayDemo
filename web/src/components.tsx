import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import type {
  Answer, AttributeScore, Demand, DriftReport, Investigation, MapPoint, Probe, QueryEvaluation, RetrievalRow, Run, ScoredPassage,
  SearchTry, Verification, WhyVerdict, WinBackAction, RunSummary, VisibilitySet, Zone,
} from "./api";
import {
  GAP_ZONES, OWNER_TEXT, OWNER_TITLE, ZONE_ORDER, ZONES, getHealth, getInvestigations, reaskRun, rescoreRun, streamRecheck,
  streamRewriteTest,
} from "./api";
import { MATCH_STEP, checkProblems, matchRows, matchVerdict, missedQuestions, moved, wordDiff, wordsIn } from "./quickwins";
import type { MatchVerdict } from "./quickwins";
import { ADDED_MIN_WEIGHT, Slider } from "./claims";
import {
  PROVENANCE_LABEL, ZONE_LABEL, ZONE_MEANING, claimShare, headline, plain, potentialText, probeLabels,
  provenanceLabel, runLabels, when,
} from "./labels";
import { tabBadge } from "./badge";
import { GLOSSARY } from "./glossary";
import { LINE, layoutMap } from "./maplabels";
import { PHONE, Popover, Term } from "./popover";
import { WhyAIMisses } from "./audit";
import { WhatItRead, WhyPanel } from "./why";
import { FleetPanel } from "./fleet";
import { FrontMargin, SamplerNote } from "./margin";
import { useReportTour } from "./guideBus";
import { measuredWhat } from "./tour";

const ZONE_FILL: Record<Zone, string> = {
  landed: "var(--landed)",
  lost_claim: "var(--win-back)",
  contested: "var(--contested)",
  unstated_intent: "var(--unstated)",
  imposed: "var(--imposed)",
  unprioritised: "var(--unprioritised)",
};

const pct = (x: number | null) => (x == null ? 0 : Math.round(x * 100));
const endorsed = (s: AttributeScore) => Math.round((s.echo_rate ?? 0) * s.n);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "n/a — <why>", with the why always the server's own words. A run saved before the server
 * supplied reasons says only "n/a" rather than a guess. */
const na = (reasons: Record<string, string> | undefined, field: string) =>
  reasons?.[field] ? `n/a — ${reasons[field]}` : "n/a";

/** How much of the site states it, or the server's reason it is not known. */
const siteShare = (s: AttributeScore) =>
  claimShare(s.claim_pages, s.claim_pages_total, s.claim_strength) ?? na(s.na_reasons, "claim_strength");

/** How often AI raised it, or the server's reason there were no answers to count. */
const aiShare = (s: AttributeScore) =>
  s.echo_rate == null ? na(s.na_reasons, "echo_rate")
    : `${s.echoes}/${s.n} mentioned · ${endorsed(s)} endorsed${s.negative_echoes > 0 ? ` · ${s.negative_echoes} negative` : ""}`;

/** Deterministic hue per name, so a company keeps its colour on every screen. */
const hue = (name: string) => [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

/**
 * The company's own website icon, captured at onboarding. When there is none, or it fails to load
 * (offline, moved, blocked), the first letter in a coloured square stands in — never a third-party
 * logo service.
 */
export function Logo({ name, url, size = 40 }: { name: string; url?: string | null; size?: number }) {
  const [failed, setFailed] = useState<string | null>(null);
  const style = { width: size, height: size, fontSize: size * 0.5 };
  if (url && failed !== url) {
    return <img className="logo" src={url} alt="" style={style} referrerPolicy="no-referrer"
                onError={() => setFailed(url)} />;
  }
  return (
    <span className="logo letter" aria-hidden style={{ ...style, background: `hsl(${hue(name)} 55% 45%)` }}>
      {(name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}

/** A collapsible section whose header already says what it found, so a closed page still reads. */
function Block({ title, found, children, open, className = "" }: {
  title: ReactNode; found: ReactNode; children: ReactNode; open?: boolean; className?: string;
}) {
  return (
    <details className={`block ${className}`} open={open}>
      <summary>
        <span className="block-title">{title}</span>
        <span className="block-found">{found}</span>
      </summary>
      <div className="block-body">{children}</div>
    </details>
  );
}

/** One titled part of a report tab, headed by what it found. */
function Section({ title, found, children, className }: {
  title: ReactNode; found: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={className ? `panel-sec ${className}` : "panel-sec"}>
      <div className="panel-sec-head">
        <h3>{title}</h3>
        <span className="block-found">{found}</span>
      </div>
      {children}
    </section>
  );
}

/** A whole run's buyer visibility or one front's: the same fields on both. */
type Vis = Pick<DriftReport, "visibility" | "tries" | "repeat_sample" | "visibility_range" | "low_confidence">;

/** The wobble, for the number's own popover: how much the re-asked questions moved between asks.
 * Null when nothing was asked twice, so there is nothing honest to say about it. */
const wobbleText = (d: Vis) => (d.tries ?? 1) > 1 && d.repeat_sample && d.visibility_range
  ? `${plural(d.repeat_sample, "of these questions was", "of these questions were")} asked ${d.tries}`
    + ` times over. On their own they scored between ${d.visibility_range[0]} and`
    + ` ${d.visibility_range[1]}, so asking the very same question again moves it about that much.`
  : null;

/** The one range under the number: where it would land if the whole run were repeated. */
const rangeText = (iv?: [number, number] | null) => !iv ? null
  : iv[0] === iv[1] ? `would stay at ${iv[0]} if we asked again` : `could be ${iv[0]}–${iv[1]} if we asked again`;

/** The same sentence for the printed summary, where nothing can be hovered. */
const printedRange = (d: Vis, iv?: [number, number] | null) =>
  [rangeText(iv), wobbleText(d)].filter(Boolean).map((t) => ` — ${t}`).join("");

const FRONT_TERM = { placed: "where_placed", aiming: "where_aiming" } as const;

/** The labelled fronts of a run, placed first; empty for one unlabelled set or an older run. */
const frontsOf = (d: DriftReport): VisibilitySet[] => (d.sets ?? []).filter((v) => v.front);

/** One short label per front. "both": the category AI places you in is the one you aim for. */
function FrontLabel({ v }: { v: VisibilitySet }) {
  if (v.front === "both") {
    return <><Term k="where_placed">Where AI places you</Term> = <Term k="where_aiming">where you aim to be</Term></>;
  }
  const k = FRONT_TERM[v.front as "placed" | "aiming"];
  return <Term k={k}>{GLOSSARY[k].term}</Term>;
}

/** The gap between the two fronts in one plain sentence, or why there is only one. `short` leaves out the
 * categories and numbers, for the header, where the strip and its rows already show them. */
function gapSentence(d: DriftReport, brand: string, short = false): string | null {
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

/** "0–10" beside a number: its bootstrap 95% confidence interval, explained one hover or tap away. */
function Ci({ iv, of }: { iv?: [number, number] | null; of: string }) {
  if (!iv) return null;
  return (
    <Term k="confidence_interval" note={`${of}: between ${iv[0]} and ${iv[1]}, 95% confident.`}>
      <small className="ci">{iv[0]}–{iv[1]}</small>
    </Term>
  );
}

/** The ONE range under a visibility number: where it would land if the whole run were repeated.
 * The per-question wobble is not a second range — it lives in the number's own popover. */
function Range({ d, iv, note }: { d: Vis; iv?: [number, number] | null; note?: string | null }) {
  if (d.visibility == null) return <>not measured</>;
  const text = rangeText(iv);
  return <Term k="confidence_interval" note={text ? undefined : note}>{text ?? "one run, no range yet"}</Term>;
}

/** The gap's significance test in words: real, not distinguishable, or too few questions to call. */
function GapVerdict({ d }: { d: DriftReport }) {
  const withheld = d.na_reasons?.visibility_gap_interval;
  if ((d.gap_real == null || !d.gap_interval) && !withheld) return null;
  return (
    <>
      {" "}
      {d.gap_real != null && d.gap_interval ? (
        <Term k="significant_gap" note={`The gap is between ${d.gap_interval[0]} and ${d.gap_interval[1]} points, 95% confident.`}>
          {d.gap_real ? "The gap is real, 95% confident." : "Not distinguishable with this sample."}
        </Term>
      ) : (
        <Term k="significant_gap" note={withheld}>Too few questions to call the gap.</Term>
      )}
    </>
  );
}

/** Buyer visibility, never a bare number when the control question says it is not to be trusted.
 * `explain` puts what the number means, and how much one question wobbles between asks, one hover
 * or tap away on the number itself — so the summary beneath it shows one range, not two. */
function Visibility({ d, explain }: { d: Vis; explain?: boolean }) {
  if (d.visibility == null) return <>n/a</>;
  const score = <>{d.visibility}<small> / 100</small></>;
  return (
    <>
      {explain ? <Term k="buyer_visibility" note={wobbleText(d)}>{score}</Term> : score}
      {d.low_confidence && <> <Confidence note={d.low_confidence} /></>}
    </>
  );
}

/** The model that answered the questions and the separate one that judged them, as the answers record. */
const modelsOf = (run: Run) => {
  const all = [run.answers, run.repeat_answers ?? []].flat();
  const list = (xs: (string | null | undefined)[]) => [...new Set(xs.filter(Boolean))].join(", ");
  return { answered: list(all.map((a) => a.model)), judged: list(all.map((a) => a.evaluator_model)) };
};

/** A score's interval as untapped potential (100 minus the score), low to high. */
const untapped = (iv?: [number, number] | null): [number, number] | null =>
  iv ? [Math.round((100 - iv[1]) * 10) / 10, Math.round((100 - iv[0]) * 10) / 10] : null;

/** One plain sentence per front: what the category is and where it came from. */
const FRONT_MEANS: Record<"placed" | "aiming" | "both", (brand: string) => string> = {
  placed: (brand) => `The category AI's own answers about ${brand} put it in.`,
  aiming: () => "The category your own homepage puts you in.",
  both: (brand) => `AI's answers about ${brand} put it in the category your homepage aims for.`,
};

/** What buyer visibility said for a front, in one clause, from its own number. */
const visSaid = (v: Vis, brand: string) => v.visibility == null ? null
  : v.visibility === 0 ? `Asked about it without the name, AI never brought ${brand} up.`
  : `Asked about it without the name, AI brought ${brand} up: ${v.visibility} of 100.`;

/** "Low confidence" in amber, never red: a caution about what the number can say, not an error. */
function Confidence({ note }: { note: string }) {
  return <Term k="low_confidence" note={note}><span className="conf">Low confidence</span></Term>;
}

/**
 * The two fronts on one 0–100 buyer-visibility line: a numbered marker each, the likely range of
 * the one that has it shaded, the gap between them dashed. A picture of the rows beneath it, which
 * carry every number in words, so it is hidden from screen readers.
 */
function PositionStrip({ fronts }: { fronts: VisibilitySet[] }) {
  const shown = fronts.filter((v) => v.visibility != null);
  if (!shown.length) return null;
  const at = shown.map((v) => v.visibility as number);
  const lo = Math.min(...at), hi = Math.max(...at);
  return (
    <div className="strip" aria-hidden="true">
      <div className="strip-track" />
      {shown.map((v) => v.interval && (
        <div key={`band-${v.front}`} className={`strip-band ${v.front}`}
             style={{ left: `${v.interval[0]}%`, width: `${Math.max(1, v.interval[1] - v.interval[0])}%` }} />
      ))}
      {shown.length > 1 && hi > lo && (
        <>
          <div className="strip-gap" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
          <span className="strip-gap-label" style={{ left: `${(lo + hi) / 2}%` }}>gap {Math.round((hi - lo) * 10) / 10}</span>
        </>
      )}
      {shown.map((v, i) => (
        <span key={v.front} className={`strip-mark ${v.front}`} style={{ left: `${v.visibility}%` }}>{i + 1}</span>
      ))}
      {[0, 50, 100].map((t) => <span key={t} className="strip-tick" style={{ left: `${t}%` }}>{t}</span>)}
    </div>
  );
}

/** One front as a row under the strip: its marker, label and category, its score, and what it means. */
function FrontRow({ v, n, brand, run }: { v: VisibilitySet; n: number; brand: string; run?: Run }) {
  return (
    <div className="front-row">
      <span className={`front-dot ${v.front}`} aria-hidden="true">{n}</span>
      <div className="front-name"><FrontLabel v={v} />: <strong>{v.category}</strong></div>
      <span className="front-score"><Visibility d={v} explain /></span>
      <p className="front-means">
        {FRONT_MEANS[v.front as "placed" | "aiming" | "both"](brand)} {visSaid(v, brand)}
        {" "}<Range d={v} iv={v.interval} note={v.interval_note} />
        {run?.sampler && <> · <FrontMargin run={run} front={v.front} /></>}
      </p>
    </div>
  );
}

/** The headline, buyer visibility and the quick wins. The whole block scrolls with the page; once it
 * is out of view a one-line summary pins itself above the tabs (Report). */
function Figures({ d, brand, run, onQuickWins }: { d: DriftReport; brand: string; run?: Run; onQuickWins?: () => void }) {
  const h = headline(d);
  const wins = d.lost_claims.length + d.unstated_intent.length;  // the Quick wins tab's claims
  const fronts = frontsOf(d);
  const gap = gapSentence(d, brand, true);
  const unsure = fronts.filter((v) => v.low_confidence);
  return (
    <div className="figures">
      <div className="fig-card headline" data-tour="headline">
        <span className="hero-num">
          {h.potential == null ? "n/a" : <>{h.potential}%</>}
        </span>
        <span className="fig-label">
          {h.potential == null ? h.label : <Term k="untapped_potential">Untapped potential</Term>}
        </span>
        <span>{h.today ?? d.na_reasons?.[h.field]}</span>
        {h.potential != null && untapped(d[`${h.field}_interval`]) && (
          <span className="muted">Could be <Ci iv={untapped(d[`${h.field}_interval`])} of="Untapped potential" /></span>
        )}
        {wins > 0 && (
          <span className="row" style={{ gap: ".3rem" }}>
            <button type="button" className="chip-link" onClick={onQuickWins}>{plural(wins, "quick win")} →</button>
            <Term k="quick_wins" icon />
          </span>
        )}
      </div>
      <div className="fig-card fronts" data-tour="fronts">
        <div className="fronts-head">
          <strong>Does AI bring {brand} up when buyers ask?</strong>
          <span className="muted"><Term k="buyer_visibility">buyer visibility</Term>, 0–100</span>
        </div>
        {fronts.length ? (
          <>
            <PositionStrip fronts={fronts} />
            {fronts.map((v, i) => <FrontRow key={v.front} v={v} n={i + 1} brand={brand} run={run} />)}
            {gap && <p className="gap-line">{gap}<GapVerdict d={d} /></p>}
            {unsure.length > 0 && (
              <details className="conf-explain">
                <summary>What does “low confidence” mean here?</summary>
                <p>For each category we also ask AI which companies lead it. If {brand} is not among them, a low
                  score says more about what AI knows than about how buyers see {brand}.</p>
                {unsure.map((v) => <p key={v.front} className="muted"><strong>{v.category}:</strong> {v.low_confidence}</p>)}
              </details>
            )}
          </>
        ) : (
          <div className="front-row">
            <span className="front-score"><Visibility d={d} explain /></span>
            <p className="front-means">
              {d.visibility == null ? d.na_reasons?.visibility
                : <Range d={d} iv={d.visibility_interval} note={d.na_reasons?.visibility_interval} />}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/** The one line that stays pinned once the header has scrolled away: the headline and each front. */
function PinnedLine({ d, run }: { d: DriftReport; run: Run }) {
  const h = headline(d);
  const fronts = frontsOf(d).filter((v) => v.visibility != null);
  return (
    <div className="pinned-line">
      <Logo name={run.profile.name} url={run.profile.logo_url} size={22} />
      <strong>{run.profile.name}</strong>
      {h.potential != null && <span><strong>{h.potential}%</strong> untapped</span>}
      {fronts.length > 0 && (
        <span className="muted">buyer visibility {fronts.map((v) => v.visibility).join(" → ")}</span>
      )}
    </div>
  );
}

/** What the pinned figures mean, in plain words with every invented term defined in place. */
function Explain({ d, brand }: { d: DriftReport; brand: string }) {
  return (
    <p className="muted" style={{ margin: 0 }}>
      <Term k="untapped_potential">Untapped potential</Term> is the share of{" "}
      {d.lens === "claim"
        ? <>what {brand}’s site says (claims on more pages count for more)</>
        : <>what {brand} wants to be known for (weighted by how much each claim matters)</>}
      {" "}that AI’s answers about {brand} do not yet say supportively.{" "}
      <Term k="buyer_visibility">Buyer visibility</Term> is a separate score: how often {brand} came up
      when a buyer asked without naming it.
      {" "}Based on {d.n_named} <Term k="brand_question">branded question</Term> answers and{" "}
      {d.n_blind} <Term k="buyer_question">unbranded question</Term> answers · source: {provenanceLabel(d.provenance)}
    </p>
  );
}

/**
 * Why an answer is left out of the scores, in words a reader can follow, or null when it counts.
 * Mirrors scoring.eligible, rule for rule; `counts` below is its yes/no.
 */
function leftOut(a: Answer | undefined, e: QueryEvaluation | undefined, brand: string): string | null {
  if (!a || !e) return "no answer came back";
  if (a.provenance === "web_research_snapshot") return "it came from a web research snapshot, not an AI answer";
  if (a.status !== "ok") return "the AI call failed";
  if (a.provenance === "live_api" && !a.search_executed) return "the AI answered from memory instead of searching the web";
  if (!e.valid) {
    return e.warnings?.includes("Off-topic answer.") ? `the AI answered about something other than ${brand}`
      : "our checker could not confirm what the answer said";
  }
  return null;
}

/** Mirrors scoring.eligible: only an answer that counts toward the scores can name anything here. */
const counts = (a: Answer, e: QueryEvaluation) => leftOut(a, e, "") == null;

/** What a reader needs to know about one kind of question, in one sentence. */
function questionKind(p: Probe, brand: string) {
  if (p.kind === "named") {
    return p.phase === "followup"
      ? `The comparison question: it names ${brand} beside the companies AI named instead. Exploratory — never counted in the scores.`
      : `A branded question: it names ${brand} but never a claim, so whatever AI says ${brand} is known for, it said on its own.`;
  }
  if (p.phase === "control") return "The control question: can the AI name the companies that lead this category at all? Never scored.";
  if (p.phase === "followup") return `A follow-up unbranded question: exploratory, never counted in the scores.`;
  return `An unbranded question: it never names ${brand}, so it shows whether AI brings ${brand} up on its own.`;
}

/**
 * "Brand question 2" as something you can read in place: hover or tap shows the question, whether
 * it counted and why not, and the AI's answer — no trip to another tab.
 */
/** A question, opened in place. `text` shows the question itself as the trigger instead of its short name. */
function QRef({ id, run, text }: { id: string; run: Run; text?: boolean }) {
  const p = run.probes.find((x) => x.id === id);
  const name = probeLabels(run.probes, run.topics)[id] ?? id;
  if (!p) return <>{name}</>;
  const a = run.answers.find((x) => x.probe_id === id), e = run.evaluations.find((x) => x.probe_id === id);
  const why = p.phase === "baseline" ? leftOut(a, e, run.profile.name) : null;
  const tab = p.kind === "named" && p.phase === "followup" ? "sources" : "questions";
  return (
    <Popover wide label={name} className={text ? "qref qtext" : "qref"} trigger={text ? p.text : name}>
      <strong className="pop-title">{name}</strong>
      <p className="muted">{questionKind(p, run.profile.name)}</p>
      <p><strong>Asked:</strong> {p.text}</p>
      {why && <p className="warn">Left out of the scores: {why}.</p>}
      {p.kind === "blind" && p.phase === "baseline" && <Searched run={run} p={p} />}
      <h4>The AI’s answer</h4>
      <p className="muted long-answer">
        {a && run.mode !== "live_api" && <span className="tag sample">sample</span>}
        {a ? plain(a.text) : "no answer"}
      </p>
      <a href={`#report-${tab}`}>Open in the {TABS.find(([t]) => t === tab)![1]} tab</a>
    </Popover>
  );
}

/** Question names and raw probe ids inside a server sentence, each made readable in place. */
function Linked({ text, run }: { text: string; run: Run }) {
  const byName = new Map<string, string>();
  for (const [id, n] of Object.entries(probeLabels(run.probes, run.topics))) {
    byName.set(n, id);
    byName.set(n.replace(/ — .*/, ""), id);
    byName.set(id, id);
  }
  const keys = [...byName.keys()].sort((x, y) => y.length - x.length).map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!keys.length) return <>{text}</>;
  const parts = text.split(new RegExp(`\\b(${keys.join("|")})\\b`));
  return <>{parts.map((t, i) => (i % 2 ? <QRef key={i} id={byName.get(t)!} run={run} /> : t))}</>;
}

/** Several question references as "A, B and C". */
const refs = (ids: string[], run: Run) => ids.map((id, i) => (
  <span key={id}>{i ? (i === ids.length - 1 ? " and " : ", ") : ""}<QRef id={id} run={run} /></span>
));

/**
 * The six zones as chips with counts. Each opens a popover listing its claims — site share, AI
 * share, the AI's own words, the questions behind them and the fix — scrolling when there are many.
 * An empty zone is greyed but still says what it means.
 */
function ZoneChips({ run }: { run: Run }) {
  const sorted = sortClaims(run.attribute_scores);
  return (
    <Section title="Your claims, grouped by what AI does with them" found="hover or tap a group to see its claims">
      <div className="chips" role="list" data-tour="zones">
        {ZONES.map((z) => {
          const rows = sorted.filter((s) => s.zone === z);
          return (
            <div role="listitem" key={z}>
              <Popover wide label={`${GLOSSARY[z].term}: ${plural(rows.length, "claim")}`}
                       className={`chip ${rows.length ? "" : "zero"}`}
                       trigger={<><span className="dot" style={{ background: ZONE_FILL[z] }} />{ZONE_LABEL[z]}
                                  <span className="chip-count">{rows.length}</span></>}>
                <strong className="pop-title">{GLOSSARY[z].term} · {plural(rows.length, "claim")}</strong>
                <p className="muted">{GLOSSARY[z].def}</p>
                {rows.length ? rows.map((s) => <ClaimDetail key={s.attribute_id} s={s} run={run} />)
                  : <p className="muted">No claim is in this group in this run.</p>}
              </Popover>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

/**
 * The excluded brand answers, in plain words: how many the headline rests on, why each was left out
 * (each question readable in place), and which way that tilts the number.
 */
function Excluded({ run }: { run: Run }) {
  const d = run.drift!;
  if (!d.excluded_named) return null;
  const brand = run.profile.name;
  const h = headline(d);
  const byReason = new Map<string, string[]>();
  for (const p of run.probes.filter((x) => x.kind === "named" && x.phase === "baseline")) {
    const why = leftOut(run.answers.find((a) => a.probe_id === p.id), run.evaluations.find((e) => e.probe_id === p.id), brand);
    if (why) byReason.set(why, [...(byReason.get(why) ?? []), p.id]);
  }
  const found = [...byReason.values()].flat().length;
  const them = d.excluded_named === 1 ? "it" : "them";
  return (
    <div className="callout excluded">
      <h4>Based on {d.n_named} of {d.named_asked} brand answers</h4>
      <p>
        {found === d.excluded_named
          ? [...byReason].map(([why, ids], i) => (
              <span key={why}>{i ? " " : ""}For {ids.length === 1 ? "one question" : `${ids.length} questions`} ({refs(ids, run)}), {why}.</span>
            ))
          : <>Left out: {d.excluded_reasons.map((r, i) => <span key={i}>{i ? "; " : ""}<Linked text={r} run={run} /></span>)}.</>}
        {" "}We left {them} out rather than guess what {them === "it" ? "it" : "they"} would have said.
      </p>
      <p className="muted">
        A left-out answer cannot count against {brand}, so this can only flatter it
        {h.value != null ? <>: read today’s {h.value}% as a best case, and the {h.potential}% untapped potential as a minimum.</> : "."}
      </p>
    </div>
  );
}

/**
 * Where these answers came from, stated before any number. A replayed run gets the loudest label
 * on the page: presenting authored answers as measured is the one failure this product cannot have.
 */
function RunSource({ run }: { run: Run }) {
  if (run.mode !== "live_api") {
    return (
      <div className="callout sample">
        <strong>SYNTHETIC DEMO — fixture replay; no live chatbot measurements; model judgment simulated.</strong>
        {" "}Every answer in this run was authored, not asked.
      </div>
    );
  }
  const { answered, judged } = modelsOf(run);
  return (
    <p className="source">
      <strong>{PROVENANCE_LABEL.live_api}</strong> — answered by {answered || "the configured model"} via
      the OpenAI Responses API with web search{judged && (judged === answered ? `, judged by the same model` : `, judged by a separate model (${judged})`)}. This
      measures that API at this moment, not the ChatGPT consumer app. Answers with no search behind
      them are excluded from scores.
    </p>
  );
}

const TABS = [
  ["overview", "Overview"], ["questions", "Questions we asked AI"], ["win-back", "Quick wins"],
  ["why", "Why AI misses you"], ["sources", "Sources & rivals"],
] as const;

/** A tab label's native tooltip, for the tab named after the terms this product invented. */
const TAB_HINT: Partial<Record<ReportTab, string>> = {
  questions: `${GLOSSARY.buyer_question.term}: ${GLOSSARY.buyer_question.def} ${GLOSSARY.brand_question.term}: ${GLOSSARY.brand_question.def}`,
};
type ReportTab = (typeof TABS)[number][0];

/** "#report-questions" opens the questions tab, so a link can land on one; the two tabs it replaced
 * ("#report-buyer", "#report-brand") land there too. */
const tabFromHash = (): ReportTab => {
  const hash = window.location.hash.replace(/^#report-(buyer|brand)$/, "#report-questions");
  return TABS.find(([t]) => hash === `#report-${t}`)?.[0] ?? "overview";
};

const sortClaims = (scores: AttributeScore[]) => [...scores].sort(
  (a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.mention_rate ?? b.echo_rate ?? 0) - (a.mention_rate ?? a.echo_rate ?? 0),
);

/**
 * One run as a product: a summary pinned at the top, then one tab per question a reader asks —
 * each fitting about one screen — with every claim and question readable in place. Same numbers
 * and data as ever; only the layout. `onRescored` enables the optional weights step; without it the
 * report is read-only.
 */
export function Report({ run, onRescored }: {
  run: Run;
  onRescored?: (r: Run) => void;
}) {
  const d = run.drift;
  const uid = useId();
  const top = useRef<HTMLDivElement>(null);
  const shown = d ? headline(d) : null;
  useReportTour({ brand: run.profile.name, today: shown?.value, potential: shown?.potential, what: measuredWhat(run.profile.name, d?.lens) });
  const [tab, setTabState] = useState<ReportTab>(tabFromHash);
  const [reasks, setReasks] = useState<Record<string, RetrievalRow["reask"]>>({});
  const reasked = (probe: string, got: RetrievalRow["reask"]) => setReasks((m) => ({ ...m, [`${run.id}:${probe}`]: got }));
  useEffect(() => {
    const follow = () => setTabState(tabFromHash());
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  useEffect(() => {
    // On a phone the tab strip scrolls sideways: keep the chosen tab in view, including one opened by a link.
    const btn = document.getElementById(`${uid}-tab-${tab}`), strip = btn?.parentElement;
    if (btn && strip) strip.scrollLeft = btn.offsetLeft - strip.offsetLeft - 16;
  }, [tab, uid]);
  const [nudge, setNudge] = useState(true);
  // The header scrolls with the page; once it is out of view a one-line summary pins above the tabs.
  const head = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(false);
  useEffect(() => {
    const el = head.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => setPinned(!e.isIntersecting && e.boundingClientRect.top < 0));
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const setTab = (t: ReportTab, focus = false) => {
    setNudge(false);
    setTabState(t);
    window.history.replaceState(null, "", `#report-${t}`);
    if (focus) document.getElementById(`${uid}-tab-${t}`)?.focus();
    // A pinned header means the reader scrolled into the previous tab; start the new one at its top.
    const head = top.current;
    if (head && head.getBoundingClientRect().top <= 0) head.parentElement?.scrollIntoView({ block: "start" });
  };
  const onKey = (e: KeyboardEvent) => {
    const i = TABS.findIndex(([t]) => t === tab);
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key];
    if (to == null) return;
    e.preventDefault();
    setTab(TABS[(to + TABS.length) % TABS.length][0], true);
  };

  const claims = run.attribute_scores.filter((s) => !s.discovered);
  // Badges say what they count, in words, and never a bare 0 that reads as a grade: a tab with
  // nothing to fix shows a tick, and one with nothing to list shows no badge.
  const badge: Record<ReportTab, string | undefined> = {
    overview: tabBadge(claims.length, "claim"),
    questions: tabBadge(run.probes.filter((p) => p.phase === "baseline").length, "question"),
    "win-back": tabBadge(winBackPlan(run).targets.length, "claim", "✓"),
    why: tabBadge(run.audit?.claims.filter((c) => c.checks.some((k) => k.status === "fail")).length, "claim", "✓"),
    sources: tabBadge(run.insights?.sources.sources.length, "site"),
  };

  return (
    <article className="report">
      <div className="report-head" ref={head}>
        <div className="row" style={{ minWidth: 0 }}>
          <Logo name={run.profile.name} url={run.profile.logo_url} size={34} />
          <div style={{ minWidth: 0 }}>
            <h2>{run.profile.name}</h2>
            <div className="muted" title={run.id}>
              {when(run.created_at)} · {run.mode === "live_api" ? PROVENANCE_LABEL.live_api : "Sample run — authored answers"}
              {run.mode === "live_api" && modelsOf(run).answered && ` · answered by ${modelsOf(run).answered}`}
              {run.mode === "live_api" && modelsOf(run).judged && `, judged by ${modelsOf(run).judged}`}
            </div>
          </div>
        </div>
        {d && <PrintSummary run={run} />}
        {d && <Figures d={d} brand={run.profile.name} run={run} onQuickWins={() => setTab("win-back")} />}
      </div>
      <div className={`report-top${pinned ? " pinned" : ""}`} ref={top}>
        {d && pinned && <PinnedLine d={d} run={run} />}
        {d && (
          <div className={`report-tabs${nudge ? " nudge" : ""}`} role="tablist" aria-label="Report sections" onKeyDown={onKey}>
            {TABS.map(([t, label], i) => (
              <button key={t} id={`${uid}-tab-${t}`} role="tab" className="rtab" aria-selected={tab === t} data-tour={`tab-${t}`}
                      style={{ "--i": i } as CSSProperties}
                      aria-controls={`${uid}-panel-${t}`} tabIndex={tab === t ? 0 : -1} onClick={() => setTab(t)}
                      title={TAB_HINT[t]}>
                {label}
                {badge[t] && <span className="rtab-count">{badge[t]}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      {d ? (
        <div className="report-panel" role="tabpanel" id={`${uid}-panel-${tab}`} aria-labelledby={`${uid}-tab-${tab}`}
             tabIndex={0}>
          {tab === "overview" && (
            <>
              <RunSource run={run} />
              <Explain d={d} brand={run.profile.name} />
              <FixLine run={run} onOpen={() => setTab("why")} />
              <ZoneChips run={run} />
              <Excluded run={run} />
              {onRescored && <Weights key={run.id} run={run} onRescored={onRescored} />}
              <HowWeChecked run={run} />
            </>
          )}
          {tab === "win-back" && (
            <>
              <FleetPanel run={run} />
              <WinBack run={run} />
              <Section title="Where the upside is" found="the biggest open claims first">
                <UpsideTable run={run} />
              </Section>
            </>
          )}
          {tab === "questions" && <div className="qboard"><BuyerQuestions run={run} /><BrandQuestions run={run} /></div>}
          {tab === "why" && <WhyTab run={run} reasks={reasks} onReasked={reasked} />}
          {tab === "sources" && (
            <>
              <CitationNetwork run={run} />
              <ShareOfVoice run={run} />
              <PositioningMapView run={run} />
              <Competitors run={run} />
              <Discovered run={run} />
            </>
          )}
        </div>
      ) : (
        <>
          <RunSource run={run} />
          <div className="callout">This run finished without a report.</div>
        </>
      )}
    </article>
  );
}

type WhySub = "searches" | "fix" | "site" | "ask";

/**
 * "Why AI misses you": one headline, a summary card per reason, then the detail behind each reason
 * on its own sub-tab: the AI's searches, the match test, the site check, and the live experiment.
 */
function WhyTab({ run, reasks, onReasked }: {
  run: Run; reasks: Record<string, RetrievalRow["reask"]>; onReasked: (probe: string, got: RetrievalRow["reask"]) => void;
}) {
  const uid = useId();
  const s = run.insights?.searches;
  const sim = run.retrieval;
  const subs = ([
    ["searches", "What the AI searched", !!s], ["fix", "Test a fix", !!sim], ["site", "Site check", true],
    ["ask", "Ask why (live)", run.mode === "live_api"],
  ] as [WhySub, string, boolean][]).filter(([, , on]) => on);
  const [sub, setSub] = useState<WhySub>(subs[0][0]);
  const open = (t: WhySub, focus = false) => {
    setSub(t);
    if (focus) document.getElementById(`${uid}-sub-${t}`)?.focus();
  };
  const onKey = (e: KeyboardEvent) => {
    const i = subs.findIndex(([t]) => t === sub);
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: subs.length - 1 }[e.key];
    if (to == null) return;
    e.preventDefault();
    open(subs[(to + subs.length) % subs.length][0], true);
  };
  const brand = run.profile.name;
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  const recorded = s ? buyer.filter((p) => s.questions[p.id]?.length) : [];
  const missed = s ? missedQuestions(s.questions, recorded.map((p) => p.id)) : [];
  const placed = new Set(buyerGroups(run)[0]?.probes.map((p) => p.id));
  const compared = sim?.rows.filter((r) => r.yours && r.rival) ?? [];
  const withFix = sim?.rows.filter((r) => r.fixed && r.yours) ?? [];
  const up = withFix.filter((r) => moved(r.yours!.score, r.fixed!.score) >= MATCH_STEP).length;
  const down = withFix.filter((r) => moved(r.yours!.score, r.fixed!.score) <= -MATCH_STEP).length;
  const checks = run.audit ? checkProblems(run.audit.claims) : null;
  const facts = (source: string) => run.audit?.entities.find((e) => e.source === source)?.status;
  const card = (t: WhySub, label: string) => (
    <button type="button" className="linky go" onClick={() => { open(t); document.getElementById(`${uid}-panel`)?.scrollIntoView({ block: "start" }); }}>{label}</button>
  );
  return (
    <>
      {s && !s.reason && recorded.length > 0 && (
        <h3 className="why-headline">
          On {missed.length} of {plural(recorded.length, "buyer question")}, none of the pages AI cited was {brand}'s.
        </h3>
      )}
      <div className="summary-cards">
        {s && !s.reason && (
          <div className="card sumcard">
            <span className="sum-title">Its searches don't reach you</span>
            <span className="big">{s.owned} <small>of {plural(s.searches.length, "search", "searches")}</small></span>
            <p>ended in an answer that cited your site.
              {placed.size > 0 && [...placed].every((id) => missed.includes(id))
                && <> None of the {placed.size} “<Term k="where_placed">where AI places you</Term>” questions did.</>}</p>
            {card("searches", "See the searches")}
          </div>
        )}
        {sim && compared.length > 0 && (
          <div className="card sumcard">
            <span className="sum-title">Your pages lose the match</span>
            <span className="big">{compared.filter(behind).length} <small>of {plural(compared.length, "question")}</small></span>
            <p>Your best page matches the question less closely than the page AI cited.
              {withFix.length > 0 && ` The suggested rewrites score higher on ${up} of the ${withFix.length} questions they target, lower on ${down}.`}</p>
            {card("fix", "See the scores")}
          </div>
        )}
        {checks && run.audit!.claims.length > 0 && (
          <div className="card sumcard">
            <span className="sum-title">Something in AI's way</span>
            <span className="big">{checks.pages} <small>of {plural(run.audit!.claims.length, "claim page")}</small></span>
            <p>{checks.failing.length ? checks.failing.slice(0, 2).map((f) => `${GLOSSARY[f.key].term} fails on ${f.n}`).join("; ") + "." : "Nothing fails."}
              {facts("Wikidata") === "found" && facts("Wikipedia") === "found" ? ` Wikipedia and Wikidata know ${brand}.`
                : facts("Wikidata") === "missing" ? " No Wikidata entry." : ""}</p>
            {card("site", "See the site check")}
          </div>
        )}
      </div>
      <div className="subtabs" role="tablist" aria-label="Why AI misses you, in detail" onKeyDown={onKey}>
        {subs.map(([t, label]) => (
          <button key={t} id={`${uid}-sub-${t}`} type="button" role="tab" aria-selected={sub === t}
                  aria-controls={`${uid}-panel`} tabIndex={sub === t ? 0 : -1} onClick={() => open(t)}>{label}</button>
        ))}
      </div>
      <div id={`${uid}-panel`} role="tabpanel" aria-labelledby={`${uid}-sub-${sub}`} className="subpanel">
        {sub === "searches" && <WhatItSearched run={run} />}
        {sub === "fix" && <TestAFix run={run} reasks={reasks} onReasked={onReasked} />}
        {sub === "site" && <WhyAIMisses run={run} />}
        {sub === "ask" && <WhyPanel run={run} />}
      </div>
    </>
  );
}

/** Top 3 landed claims, most-endorsed first: what AI already says for you. */
const topWins = (scores: AttributeScore[]) => scores
  .filter((s) => s.zone === "landed")
  .sort((a, b) => (b.echo_rate ?? 0) - (a.echo_rate ?? 0))
  .slice(0, 3);

/** Top 3 open claims, in the same order as "Where the upside is". */
const topFixes = (scores: AttributeScore[]) => scores
  .filter((s) => GAP_ZONES.includes(s.zone))
  .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
  .slice(0, 3);

/**
 * "Download summary (PDF)": mounts a one-page summary on <body> and opens the browser's print
 * dialog, where "Save as PDF" makes the file. Print CSS shows only the summary; on screen it never
 * renders, so there is no second copy of the report to keep in sync.
 */
function PrintSummary({ run }: { run: Run }) {
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    if (!printing) return;
    const done = () => setPrinting(false);
    window.addEventListener("afterprint", done);
    window.print();
    return () => window.removeEventListener("afterprint", done);
  }, [printing]);
  return (
    <>
      <button className="ghost" onClick={() => setPrinting(true)}>Download summary (PDF)</button>
      {printing && createPortal(<ExecSummary run={run} />, document.body)}
    </>
  );
}

/** The one-page summary itself: logo, the potential with the real score beneath, 3 wins, 3 fixes. */
function ExecSummary({ run }: { run: Run }) {
  const d = run.drift!;
  const h = headline(d);
  const wins = topWins(run.attribute_scores);
  const fixes = topFixes(run.attribute_scores);
  const live = run.mode === "live_api";
  return (
    <section className="exec-summary">
      <div className="row">
        <Logo name={run.profile.name} url={run.profile.logo_url} size={48} />
        <div>
          <h2>{run.profile.name}</h2>
          <div className="muted">How AI answer engines describe {run.profile.name} — executive summary</div>
        </div>
      </div>
      <div className="figure potential">
        <div className="label">{h.label}</div>
        <div className="value">
          {h.potential == null ? "n/a" : `${h.potential}%`}
          {h.potential != null && <small> untapped potential</small>}
        </div>
        <div className="today">{h.today ?? d.na_reasons?.[h.field]}</div>
      </div>
      {frontsOf(d).length ? (
        <p className="exec-vis">
          {frontsOf(d).map((v) => (
            <span key={v.front}>
              <strong>{v.front === "both" ? "Where AI places you = where you aim to be"
                : GLOSSARY[FRONT_TERM[v.front as "placed" | "aiming"]].term} ({v.category}):</strong>{" "}
              <Visibility d={v} />{v.visibility != null && printedRange(v, v.interval)}
              {v.low_confidence && <><br /><span className="muted">{v.low_confidence}</span></>}
              <br />
            </span>
          ))}
          {gapSentence(d, run.profile.name)}
        </p>
      ) : (
        <p className="exec-vis">
          <strong>Buyer visibility:</strong> <Visibility d={d} />
          {d.visibility == null ? ` — ${d.na_reasons?.visibility ?? "not measured"}`
            : printedRange(d, d.visibility_interval)}
          {d.low_confidence && <><br /><span className="muted">{d.low_confidence}</span></>}
        </p>
      )}
      <div className="exec-cols">
        <div>
          <h3>Top wins — AI already says it</h3>
          {wins.length ? (
            <ol>{wins.map((s) => (
              <li key={s.attribute_id}><strong>{s.label}</strong><div className="muted">{aiShare(s)}</div></li>
            ))}</ol>
          ) : <p className="muted">No claim has landed yet.</p>}
        </div>
        <div>
          <h3>Top fixes — where the upside is</h3>
          {fixes.length ? (
            <ol>{fixes.map((s) => (
              <li key={s.attribute_id}>
                <strong>{s.label}</strong> <span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span>
                <div className="muted">{ZONE_MEANING[s.zone]}</div>
              </li>
            ))}</ol>
          ) : <p className="muted">No open opportunity: every claim has landed or is unweighted.</p>}
        </div>
      </div>
      <p className="exec-foot">
        Source: <strong>{live ? PROVENANCE_LABEL.live_api : "SYNTHETIC SAMPLE — authored answers, not measured"}</strong>
        {live && modelsOf(run).answered && ` · answered by ${modelsOf(run).answered}`}
        {" "}· run {when(run.created_at)} · {d.n_named} brand and {d.n_blind} buyer answers
        · printed {new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
        <br />Independent portfolio demo.
      </p>
    </section>
  );
}

/**
 * Intent weights on the finished run. The server re-scores the saved answers — no question is
 * re-asked and no model is called — and refuses (409) a run it cannot re-score, in its own words.
 */
function Weights({ run, onRescored }: { run: Run; onRescored: (r: Run) => void }) {
  const claims = run.attribute_scores.filter((s) => !s.discovered);
  const added = new Set((run.attributes ?? []).filter((a) => a.added_by_user).map((a) => a.id));
  const [w, setW] = useState<Record<string, number>>(
    () => Object.fromEntries(claims.map((s) => [s.attribute_id, s.intended_weight ?? 0])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const weighted = claims.filter((s) => (s.intended_weight ?? 0) > 0).length;
  const submit = () => {
    setBusy(true); setError(null);
    rescoreRun(run.id, w).then(onRescored).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  return (
    <Block title="Optional: weight what you want to be known for"
           found={weighted ? `${plural(weighted, "claim")} weighted · headline is alignment`
             : "nothing weighted · headline is claim echo"}>
      <p className="lede">
        Move a slider for each claim you want to be known for, then re-score. This re-scores this
        run’s saved answers: <strong>no new AI calls are made</strong>, nothing is paid, and no
        question is re-asked.
      </p>
      <div className="weights">
        {claims.map((s) => (
          <div className="weight-row" key={s.attribute_id}>
            <span>{s.label}</span>
            <Slider id={`rw-${run.id}-${s.attribute_id}`} label={`Intent for ${s.label}`}
                    min={added.has(s.attribute_id) ? ADDED_MIN_WEIGHT : 0}
                    value={w[s.attribute_id] ?? 0} disabled={busy}
                    onChange={(v) => setW((x) => ({ ...x, [s.attribute_id]: v }))} />
          </div>
        ))}
      </div>
      {error && <div className="callout error">{error}</div>}
      <div className="row">
        <button className="primary" onClick={submit} disabled={busy}>
          {busy ? "Re-scoring…" : "Re-score this run"}
        </button>
        <span className="muted">Re-scores saved answers only — no new AI calls.</span>
      </div>
    </Block>
  );
}

/**
 * How AI raises a claim. Total width is how OFTEN AI raises it. The zone-coloured segment is
 * endorsements (echo_rate, what drives landed and alignment), the grey one neutral mentions, and
 * the red one criticism.
 */
function AiBar({ s }: { s: AttributeScore }) {
  return (
    <span className="bar-track thin" aria-hidden>
      <span className="bar" style={{ width: `${pct(s.echo_rate)}%`, background: ZONE_FILL[s.zone] }} />
      <span className="bar" style={{ width: `${Math.max(0, pct(s.mention_rate) - pct(s.echo_rate) - pct(s.negative_rate))}%`, background: "#c9d1d9" }} />
      <span className="bar neg" style={{ width: `${pct(s.negative_rate)}%` }} />
    </span>
  );
}

const standing = (s: AttributeScore) =>
  s.discovered ? "discovered from the answers"
    : s.intended_weight ? `intent ${s.intended_weight}`
    : s.claim_pages > 0 || (s.claim_strength ?? 0) > 0 ? "on your site, not weighted"
    : "not claimed by you";

/** Every claim as a card; hovering or tapping one shows everything about it in place. */
function ClaimCards({ scores, run }: { scores: AttributeScore[]; run: Run }) {
  return (
    <div className="claim-cards">
      {sortClaims(scores).map((s) => (
        <Popover key={s.attribute_id} wide label={s.label} className="claim-card"
                 trigger={<>
                   <span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span>
                   <strong>{s.label}</strong>
                   <AiBar s={s} />
                   <span className="muted">Site: {siteShare(s)}</span>
                   <span className="muted">AI: {aiShare(s)}</span>
                   <span className="muted">{standing(s)}</span>
                 </>}>
          <ClaimDetail s={s} run={run} />
        </Popover>
      ))}
    </div>
  );
}

/**
 * Everything about one claim: what the site says, what AI said and where, and its win-back fix.
 * One row in a zone chip's popover; every question it cites opens in place.
 */
function ClaimDetail({ s, run }: { s: AttributeScore; run: Run }) {
  const site = (run.attributes ?? []).find((a) => a.id === s.attribute_id);
  const fix = winBackPlan(run).actions.find((a) => a.attribute_id === s.attribute_id);
  return (
    <div className="claim-row">
      <div className="claim-row-head">
        <strong>{s.label}</strong>
        <span className="muted">{standing(s)}</span>
      </div>
      {s.description && <p>{s.description}</p>}
      <AiBar s={s} />
      <p className="muted">Your site: {siteShare(s)}</p>
      <p className="muted">AI: {aiShare(s)} <Term k="endorsed" icon /></p>
      {s.quotes.length > 0 ? (
        <>
          <h4>In the AI’s own words</h4>
          {s.quotes.map((q, i) => <p className="quote" key={i}>{plain(q)}</p>)}
        </>
      ) : <p className="muted">No word-for-word quote from an AI answer supports this claim.</p>}
      {s.probe_ids.length > 0 && <p className="muted">Raised in {refs(s.probe_ids, run)}.</p>}
      {site && site.claim_quotes.length > 0 && (
        <>
          <h4>What your site says</h4>
          {site.claim_quotes.map((q, i) => <p className="quote" key={i}>{q}</p>)}
        </>
      )}
      <p><strong>{OWNER_TITLE[s.owner]}.</strong> {OWNER_TEXT[s.owner]}</p>
      {s.limitations.map((l, i) => <p className="warn" key={i}>{l}</p>)}
      {fix && (
        <>
          <h4>Quick win</h4>
          <FixCard a={fix} run={run} />
        </>
      )}
    </div>
  );
}

/** "Where the upside is": the biggest open claims first, one compact row each. The diagnosis they
 * share is said once; each row opens everything about its claim. */
function UpsideTable({ run }: { run: Run }) {
  const gaps = run.attribute_scores
    .filter((s) => GAP_ZONES.includes(s.zone))
    .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
    .slice(0, 4);
  if (!gaps.length) {
    return <div className="card muted">No open opportunity: every claim has landed or is unweighted.</div>;
  }
  const owners = [...new Set(gaps.map((s) => s.owner))];
  const shared = owners.length === 1 ? owners[0] : null;
  return (
    <div className="stack" style={{ gap: ".5rem" }}>
      {shared && (
        <p style={{ margin: 0 }}>
          {gaps.length > 1 ? `All ${gaps.length} are` : "It is"} <strong>{OWNER_TITLE[shared].toLowerCase()}s</strong>: {OWNER_TEXT[shared]}
          {shared === "messaging_gap" && " Not an AI problem: your own copy does not state this clearly enough to be repeated."}
        </p>
      )}
      <div className="table-scroll">
        <table className="compact">
          <thead><tr><th>Claim</th><th>Type</th>{!shared && <th>Why</th>}<th>Your site</th><th>AI</th></tr></thead>
          <tbody>
            {gaps.map((s) => (
              <tr key={s.attribute_id}>
                <td><Popover wide label={s.label} className="linky row-open" trigger={s.label}><ClaimDetail s={s} run={run} /></Popover>
                  {s.discovered && <span className="muted"> (AI's own)</span>}
                  {s.quotes[0] && <p className="quote small-quote">{plain(s.quotes[0])}</p>}
                  {s.limitations.filter((l) => l.includes("does not endorse it")).map((l, i) => <p className="warn" key={i} style={{ margin: 0 }}>{l}</p>)}
                </td>
                <td><Term k={s.zone}><span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span></Term></td>
                {!shared && <td><strong>{OWNER_TITLE[s.owner]}.</strong> {OWNER_TEXT[s.owner]}</td>}
                <td>{s.discovered ? "Found in the answers, not on the site" : siteShare(s)}</td>
                <td>{aiShare(s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ margin: 0 }}>Open a claim for AI's own words and all its evidence.</p>
    </div>
  );
}

/**
 * The stretch of an answer around the first mention of a name, as plain text, so the reader can see
 * how it came up: a recommendation, a passing example, or only a citation's hostname. Falls back to
 * the raw text when stripping the Markdown removed the only mention (a name inside a link's URL).
 */
function mention(text: string, name: string): [string, string, string] | null {
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

/**
 * Every company named in a buyer answer, beside the line that names it, and what AI said when asked
 * to compare.
 *
 * A name here is only what the evidence supports: the model named it in an answer to a question that
 * never named the company. Many such names are obscure products a search happened to surface, or a
 * citation's hostname, so the panel neither calls them competitors nor claims they were recommended
 * — the line is shown so the reader judges each one. It ranks only when a name genuinely repeats
 * across answers; when each appears once, any order would just be the first answer's order.
 *
 * In replay the names are authored fixture labels and the panel says so — a sentence asserting
 * measured behaviour is believed over the banner at the top of the page, and this product's whole
 * claim is that it never presents authored evidence as measured evidence.
 */
export function Competitors({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const topicOf = new Map(run.topics.map((t) => [t.id, t.label]));
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const evals = new Map(run.evaluations.map((e) => [e.probe_id, e]));
  const named = new Map<string, { name: string; count: number; topic: string;
                                   where: [string, string, string] | null }>();
  for (const p of run.probes.filter((x) => x.kind === "blind" && x.phase === "baseline")) {
    const a = answers.get(p.id), e = evals.get(p.id);
    if (!a || !e || !counts(a, e)) continue;
    for (const name of new Set(e.competitor_recommendations)) {
      const row = named.get(name.toLowerCase());
      if (row) row.count += 1;
      else named.set(name.toLowerCase(), { name, count: 1, topic: topicOf.get(p.topic_id) ?? p.topic_id,
                                           where: mention(a.text, name) });
    }
  }
  const repeats = [...named.values()].some((r) => r.count > 1);
  // A stable sort: names seen once keep the order they appeared in.
  const rows = [...named.values()].sort((x, y) => (repeats ? y.count - x.count : 0));
  const comparison = run.probes.find((p) => p.kind === "named" && p.phase === "followup");
  const answer = comparison && answers.get(comparison.id);
  // "Nobody was named" and "nobody was asked" are different findings. With no weighted claim there
  // are no buyer questions at all, and an empty set then means silence, not absence.
  const askedBuyerQuestions = run.probes.some((p) => p.kind === "blind" && p.phase === "baseline");
  const title = "Who AI named instead";
  if (!rows.length) {
    return (
      <Section title={title} found="none named">
        <p className="muted" style={{ margin: 0 }}>
        {!askedBuyerQuestions
          ? "No unbranded question was asked — nothing is weighted as intended — so the buyer axis was not measured and no other company could be named."
          : replay
            ? "This sample scenario names no competitor in its authored buyer answers. Replay never asks the comparison question either: that round exists only in a live run."
            : "No other company was named in any buyer answer that counts toward the scores, so there was nothing to compare against and no comparison question was asked."}
        </p>
      </Section>
    );
  }
  const top = rows[0];
  const namedTable = (shown: typeof rows) => (
    <table className="named">
      <thead>
        <tr><th>Company</th>{repeats && <th>Answers</th>}<th>Buyer topic</th><th>Where the answer names it</th></tr>
      </thead>
      <tbody>
        {shown.map((r) => (
          <tr key={r.name}>
            <td><strong>{r.name}</strong></td>
            {repeats && <td>{r.count}</td>}
            <td className="muted">{r.topic}</td>
            <td className="muted">
              {r.where ? <>{r.where[0]}<strong>{r.where[1]}</strong>{r.where[2]}</> : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <Section title={title}
           found={`${plural(rows.length, "company", "companies")} named${repeats ? ` · most often ${top.name} (${top.count})` : ""}`}>
      <p className="muted" style={{ margin: "0 0 .6rem" }}>
        {replay
          ? "Authored sample data, not a measurement: no model volunteered these names. A live run"
            + " puts here the brands the model itself offered when a buyer described what you do"
            + " without naming you, and only a live run asks the comparison question below."
          : `Every company the model named when a buyer asked about what ${run.profile.name} does`
            + " without naming it. Being named is not being recommended, or being a competitor:"
            + " each sits beside the part of the answer that names it, so judge it yourself."}
        {" "}
        {repeats
          ? "Sorted by how many answers named it; the rest were named once, in the order they appeared."
          : "Each was named in one answer only, so this is the order they appeared, not a ranking."}
      </p>
      {namedTable(rows.slice(0, SHOWN_NAMED))}
      {rows.length > SHOWN_NAMED && (
        <details>
          <summary className="muted">Show the other {plural(rows.length - SHOWN_NAMED, "company", "companies")}</summary>
          {namedTable(rows.slice(SHOWN_NAMED))}
        </details>
      )}
      {comparison && (
        <>
          <h4 className="muted" style={{ marginTop: "1rem" }}>
            Follow-up question, built from those names (exploratory — not counted in alignment)
          </h4>
          <QuestionRow p={comparison} name="Follow-up" answer={answer || undefined} replay={replay} />
        </>
      )}
    </Section>
  );
}

/** "A", "A and B", "A, B and C". */
const listed = (xs: string[]) => xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`;

const SAMPLE_NOTE = "Authored sample data, not a measurement: a live run fills this from the model's own answers.";

/** Brand vs the most-recommended competitors, on the buyer questions that count. One bar per name. */
function ShareOfVoice({ run }: { run: Run }) {
  const v = run.insights?.voice;
  const title = <><Term k="share_of_voice">Share of voice</Term> on unbranded questions</>;
  if (!v) return null;
  if (v.reason) {
    return (
      <Section title={title} found="not measured">
        <p className="muted" style={{ margin: 0 }}>{v.reason}</p>
      </Section>
    );
  }
  const top = v.rivals.filter((r) => r.count === v.rivals[0].count);
  const others = v.tied_top - top.length;
  const rivalText = v.tied_top > 1
    ? `${listed([...top.map((r) => r.name), ...(others ? [plural(others, "other")] : [])])} ${v.rivals[0].count} each`
    : `${top[0].name} ${plural(top[0].count, "time")}`;
  const bars = [{ name: v.brand, count: v.brand_recommended, brand: true },
                ...v.rivals.map((r) => ({ ...r, brand: false }))];
  return (
    <Section title={title}
           found={`On ${v.questions} unbranded questions, AI recommended ${v.brand} ${plural(v.brand_recommended, "time")} and ${rivalText}`}>
      <p className="muted" style={{ margin: 0 }}>
        {run.mode !== "live_api" && <>{SAMPLE_NOTE} </>}
        How many of the {v.questions} unbranded questions that count got an answer recommending each company. None
        of those questions named {v.brand}; a mention without a recommendation does not count, and a company
        counts once per answer, however often it repeats.
      </p>
      <div className="sov" role="list" aria-label={`Answers recommending each company, out of ${v.questions}`}>
        {bars.map((b) => (
          <div key={b.name} role="listitem" className="sov-row" title={`${b.name}: recommended in ${b.count} of ${v.questions} answers`}>
            <span className={b.brand ? "sov-name brand" : "sov-name"}>{b.name}</span>
            <span className="sov-track">
              <span className={b.brand ? "sov-bar brand" : "sov-bar"} style={{ width: `${(100 * b.count) / v.questions}%` }} />
            </span>
            <span className="sov-count">{b.count} / {v.questions}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

const MAP_W = 360, MAP_H = 300, MAP_PAD = 36, MAP_FONT = 12;

let measurer: CanvasRenderingContext2D | null | undefined;
/** A label's real width in map units (the SVG is MAP_W units wide at a 12-unit font), in the page's
 * own font. Only without a canvas does it fall back to a generous estimate. */
const measure = (text: string, bold = false) => {
  measurer ??= document.createElement("canvas").getContext("2d");
  if (!measurer) return text.length * MAP_FONT * 0.65;
  measurer.font = `${bold ? 650 : 400} ${MAP_FONT}px ${getComputedStyle(document.body).fontFamily}`;
  return measurer.measureText(text).width;
};

/** An axis in words, above or below the map, never inside it: a claim the axis measures (a live
 * map), or its two ends (the authored sample). */
const axisName = (ends: string[], across: boolean) => {
  const dir = across ? "→ Across:" : "↑ Up:";
  return ends.length === 1 ? `${dir} talks more about “${ends[0]}”`
    : ends.length === 2 ? `${dir} from “${ends[0]}” to “${ends[1]}”`
    : `${dir} drawn before axes were named after your claims; measure again to name it`;
};

/** What one dot was built from, verbatim, and how close it sits to the brand as AI describes it. */
function PointDetail({ p, title, site, brand, sample }: {
  p: MapPoint; title: string; site: boolean; brand: string; sample: boolean;
}) {
  const n = p.sentences.length;
  return (
    <>
      <strong className="pop-title">{title}</strong>
      <p className="muted">
        {sample && <><span className="tag sample">sample</span> Placed by hand, not computed. </>}
        {p.kind === "seen" ? `Built from ${plural(n, "sentence")} in AI's answers about ${brand}.`
          : p.kind === "intended" ? (site ? `Built from ${plural(n, "positioning line")} on your site.`
            : `Built from the ${plural(n, "claim")} you weighted; a heavier weight pulls harder.`)
          : `Built from ${plural(n, "sentence")} in buyer answers that name ${p.name}.`}
      </p>
      {p.similarity != null && (
        <p>Similarity to how AI describes {brand}: <strong>{p.similarity.toFixed(2)}</strong> (1 is the same
          meaning, 0 unrelated).</p>
      )}
      {p.sentences.map((s) => <p key={s} className="quote">{s}</p>)}
    </>
  );
}

/**
 * The positioning map (positioning.py): the brand as AI describes it, as its site describes it and
 * each rival, flattened to two axes by meaning. One arrow is the drift. Every dot, and its name in
 * the legend, opens the sentences it was built from. A picture of similarity, never a score.
 */
function PositioningMapView({ run }: { run: Run }) {
  const m = run.positioning;
  if (!m) return null;
  const brand = run.profile.name, sample = m.provenance !== "live_api", site = m.aim !== "intended";
  const aim = site ? "where your site aims" : "where you want to be";
  const found = m.reason ? "not drawn"
    : `AI places ${brand} closest to ${listed(m.closest)}`
      + (m.toward ? `; ${site ? "your site aims" : "you want to be"} further toward “${m.toward}”`
        : `; ${aim} is somewhere else on the map`);
  const body = () => {
    if (m.reason) return <p className="muted" style={{ margin: 0 }}>{m.reason}</p>;
    const order = { seen: 0, intended: 1, rival: 2 };
    const pts = [...m.points].sort((a, b) => order[a.kind] - order[b.kind] || (b.similarity ?? 0) - (a.similarity ?? 0));
    const mx = Math.max(...pts.map((p) => Math.abs(p.x)), 1e-9), my = Math.max(...pts.map((p) => Math.abs(p.y)), 1e-9);
    const scale = Math.min((MAP_W / 2 - MAP_PAD) / mx, (MAP_H / 2 - MAP_PAD) / my);
    // bold widths for every text: the brand's labels and the axis names are bold, and wider is safe
    const at = layoutMap(pts.map((p) => ({ x: MAP_W / 2 + p.x * scale, y: MAP_H / 2 - p.y * scale,
                                           r: p.kind === "rival" ? 7 : 9, text: p.kind === "intended" ? aim : p.name })),
                         MAP_W, MAP_H, axisName(m.y_axis, false), axisName(m.x_axis, true), (t) => measure(t, true), [0, 1]);
    const dots = at.dots.map((d, i) => ({ ...d, p: pts[i] }));
    const { labels, height, top } = at;
    const [seenDot, aimDot] = dots;
    const dx = aimDot.x - seenDot.x, dy = aimDot.y - seenDot.y, len = Math.hypot(dx, dy);
    const ux = dx / len, uy = dy / len, tip = [aimDot.x - ux * (aimDot.r + 2), aimDot.y - uy * (aimDot.r + 2)];
    const title = (d: (typeof dots)[number]) => d.p.kind === "seen" ? `${brand}, as AI describes it`
      : d.p.kind === "intended" ? `${brand}, ${aim}` : `${d.p.name}, as AI describes it`;
    return (
      <>
        <p className="muted" style={{ margin: 0 }}>
          {sample && <>{SAMPLE_NOTE} The dots were placed by hand. </>}
          A <Term k="positioning_map"
                  note={m.explained != null && `These two axes show ${Math.round(m.explained * 100)}% of the differences between the dots; the rest is flattened away.`}>
            similarity picture</Term>, not a measurement: dots close together were described in similar words.
          The arrow runs from where AI places {brand} to {aim}. Tap a dot for the sentences behind it.
        </p>
        <div className="pmap" style={{ aspectRatio: `${MAP_W} / ${height}` }}>
          <svg viewBox={`0 0 ${MAP_W} ${height}`} aria-hidden="true">
            {at.up.lines.map((t, j) => (
              <text key={t} className="pmap-title" x={MAP_W / 2} y={at.up.y + j * LINE} textAnchor="middle">{t}</text>
            ))}
            {at.across.lines.map((t, j) => (
              <text key={t} className="pmap-title" x={MAP_W / 2} y={at.across.y + j * LINE} textAnchor="middle">{t}</text>
            ))}
            <g transform={`translate(0 ${top})`}>
            <rect className="pmap-frame" x={0} y={0} width={MAP_W} height={MAP_H} />
            <line className="pmap-axis" x1={MAP_W / 2} y1={0} x2={MAP_W / 2} y2={MAP_H} />
            <line className="pmap-axis" x1={0} y1={MAP_H / 2} x2={MAP_W} y2={MAP_H / 2} />
            {len > seenDot.r + aimDot.r + 4 && (
              <>
                <line className="pmap-drift" x1={seenDot.x + ux * (seenDot.r + 2)} y1={seenDot.y + uy * (seenDot.r + 2)}
                      x2={tip[0] - ux * 8} y2={tip[1] - uy * 8} />
                <polygon className="pmap-head" points={`${tip[0]},${tip[1]} ${tip[0] - ux * 10 - uy * 5},${tip[1] - uy * 10 + ux * 5} ${tip[0] - ux * 10 + uy * 5},${tip[1] - uy * 10 - ux * 5}`} />
              </>
            )}
            {dots.map((d) => <circle key={`${d.p.kind}-${d.p.name}`} className={`pmap-dot ${d.p.kind}`} cx={d.x} cy={d.y} r={d.r} />)}
            {labels.map((l) => (
              <g key={l.dot}>
                {l.lead && <line className="pmap-lead" x1={l.lead[0]} y1={l.lead[1]} x2={l.lead[2]} y2={l.lead[3]} />}
                {l.lines.map((t, j) => (
                  <text key={t} className={`pmap-label ${dots[l.dot].p.kind}`} x={l.box[0]}
                        y={l.box[1] + LINE * (j + 1) - 3.5}>{t}</text>
                ))}
              </g>
            ))}
            </g>
          </svg>
          {dots.map((d) => (
            <span key={`${d.p.kind}-${d.p.name}`} className="pmap-hit"
                  style={{ left: `${(100 * d.x) / MAP_W}%`, top: `${(100 * (top + d.y)) / height}%` }}>
              <Popover wide label={title(d)} className="pmap-tap"
                       trigger={<span className="sr-only">{title(d)}</span>}>
                <PointDetail p={d.p} title={title(d)} site={site} brand={brand} sample={sample} />
              </Popover>
            </span>
          ))}
        </div>
        {at.moved && (
          <p className="muted" style={{ margin: 0 }}>
            Dots that sat on top of each other are drawn a little apart, so each can carry its name.
          </p>
        )}
        <ul className="pmap-legend">
          {dots.map((d) => (
            <li key={`${d.p.kind}-${d.p.name}`}>
              <Popover wide label={title(d)} className="chip"
                       trigger={<>
                         <span className={`pmap-swatch ${d.p.kind}`} aria-hidden="true" />
                         {d.p.kind === "seen" ? `${brand}, as AI sees it` : d.p.kind === "intended" ? aim[0].toUpperCase() + aim.slice(1) : d.p.name}
                       </>}>
                <PointDetail p={d.p} title={title(d)} site={site} brand={brand} sample={sample} />
              </Popover>
            </li>
          ))}
        </ul>
        {m.notes.map((n) => <p key={n} className="muted" style={{ margin: 0 }}>{n}</p>)}
      </>
    );
  };
  return (
    <Block open={!window.matchMedia(PHONE).matches} title="Positioning map" found={found}>
      {body()}
    </Block>
  );
}

const SHOWN_NAMED = 3;

type Source = NonNullable<Run["insights"]>["sources"]["sources"][number];

const KIND_LABEL: Record<Source["kind"], string> = {
  owned: "your site", rival: "a rival's site", review: "review site", community: "community",
  media: "media or blog", other: "other site",
};
const SHOWN_GAPS = 6;
/** The fixtures' fictional sources (RFC 2606 hosts): never linked, since there is no page to open. */
const placeholder = (domain: string) => /(^|\.)example\.(com|net|org)(\/|$)/.test(domain);

/** Up to four rival initials in a row, the rest as "+n"; each names its rival on hover. */
function Avatars({ rivals }: { rivals: Source["rivals"] }) {
  const shown = rivals.slice(0, 4);
  return (
    <span className="avatars" title={rivals.map((r) => r.name).join(", ")}>
      {shown.map((r) => <Logo key={r.name} name={r.name} size={22} />)}
      {rivals.length > shown.length && <span className="avatars-more">+{rivals.length - shown.length}</span>}
      <span className="sr-only">{listed(rivals.map((r) => r.name))}</span>
    </span>
  );
}

/** One site that AI cites beside rivals but never beside the brand; opening it shows the answers that cited it. */
function GapSource({ r, rank, run, names }: { r: Source; rank: number; run: Run; names: Record<string, string> }) {
  const probes = new Map(run.probes.map((p) => [p.id, p]));
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  return (
    <details className="src">
      <summary>
        <span className="src-rank">{rank}</span>
        <span className="src-name">
          <strong>{r.domain}</strong>
          <span className="muted">{KIND_LABEL[r.kind]} · {plural(r.buyer, "buyer answer")}</span>
        </span>
        <Avatars rivals={r.rivals} />
      </summary>
      <div className="src-body">
        <p style={{ margin: 0 }}>
          Cited beside {listed(r.rivals.map((x) => x.count > 1 ? `${x.name} (${x.count})` : x.name))},
          never in an answer that mentions {run.profile.name}.
        </p>
        <p className="muted" style={{ margin: 0 }}>
          <Term k="source_type">Site type</Term>: {KIND_LABEL[r.kind]}
          {!placeholder(r.domain) && <> · <a href={r.url} target="_blank" rel="noreferrer">open the page</a></>}
        </p>
        <div>
          {r.probes.map((id) => probes.get(id) && (
            <QuestionRow key={id} p={probes.get(id)!} name={names[id] ?? id} answer={answers.get(id)}
                         replay={run.mode !== "live_api"} />
          ))}
        </div>
      </div>
    </details>
  );
}

const MAP_SOURCES = 8, MAP_RIVALS = 6, MAP_ROW = 30;

/**
 * Brands on the left, the sites AI cited on the right, one line per pairing, thicker for more
 * buyer answers. Hovering a name dims everything it is not linked to. Wide screens only: on a
 * phone the ranked list above says the same thing.
 */
function CitationMap({ run, sources, gaps }: { run: Run; sources: Source[]; gaps: Set<string> }) {
  const [hot, setHot] = useState<string | null>(null);
  const brand = run.profile.name;
  // The sites that skip the brand first, then the most-cited, kept in the list's order.
  const keep = new Set([...new Set([...sources.filter((r) => gaps.has(r.domain)), ...sources.filter((r) => r.buyer > 0)])]
    .slice(0, MAP_SOURCES));
  const right = sources.filter((r) => keep.has(r));
  const weight = new Map<string, number>();
  for (const r of right) for (const x of r.rivals) weight.set(x.name, (weight.get(x.name) ?? 0) + x.count);
  // Each site's most-named rival first, so no site on the map is left without a line, then the rest by weight.
  const firsts = new Set(right.flatMap((r) => r.rivals.slice(0, 1).map((x) => x.name)));
  const rivals = [...new Set([...firsts, ...[...weight].sort((a, b) => b[1] - a[1]).map(([n]) => n)])];
  const left = [brand, ...rivals.slice(0, Math.max(MAP_RIVALS, firsts.size))];
  const edges = right.flatMap((r, j) => [
    ...(r.with_brand ? [{ from: 0, to: j, w: r.with_brand }] : []),
    ...r.rivals.filter((x) => left.includes(x.name)).map((x) => ({ from: left.indexOf(x.name), to: j, w: x.count })),
  ]);
  if (!right.length || edges.length === 0) return null;
  const rows = Math.max(left.length, right.length);
  const y = (i: number, n: number) => 20 + (i + (rows - n) / 2) * MAP_ROW;
  const lit = (from: number, to: number) => !hot || hot === left[from] || hot === right[to].domain;
  const dim = (name: string) => hot && hot !== name
    && !edges.some((e) => (left[e.from] === name || right[e.to].domain === name) && lit(e.from, e.to));
  return (
    <figure className="cmap">
      <svg viewBox={`0 0 640 ${rows * MAP_ROW + 20}`} role="img"
           aria-label={`Which brands each cited site appeared beside, for ${brand} and its rivals`}>
        {edges.map((e) => (
          <line key={`${e.from}-${e.to}`} x1={170} y1={y(e.from, left.length)} x2={430} y2={y(e.to, right.length)}
                className={e.from === 0 ? "edge brand" : "edge"} strokeWidth={1 + e.w}
                opacity={lit(e.from, e.to) ? 1 : 0.12}>
            <title>{`${left[e.from]} ← ${right[e.to].domain}: ${plural(e.w, "buyer answer")}`}</title>
          </line>
        ))}
        {left.map((n, i) => (
          <g key={n} className={i === 0 ? "node brand" : "node"} opacity={dim(n) ? 0.3 : 1}
             onMouseEnter={() => setHot(n)} onMouseLeave={() => setHot(null)}>
            <circle cx={170} cy={y(i, left.length)} r={5} />
            <text x={160} y={y(i, left.length)} dy=".35em" textAnchor="end">{n}</text>
          </g>
        ))}
        {right.map((r, j) => (
          <g key={r.domain} className={gaps.has(r.domain) ? "node gap" : r.owned ? "node brand" : "node"} opacity={dim(r.domain) ? 0.3 : 1}
             onMouseEnter={() => setHot(r.domain)} onMouseLeave={() => setHot(null)}>
            <circle cx={430} cy={y(j, right.length)} r={5} />
            <text x={440} y={y(j, right.length)} dy=".35em">{r.domain.length > 26 ? `${r.domain.slice(0, 25)}…` : r.domain}</text>
          </g>
        ))}
      </svg>
      <figcaption className="muted">
        <Term k="citation_map">Citation map</Term>: each line joins a brand to a site cited in a buyer answer
        that named it; thicker means more answers. Red dots are the sites that skip {brand}. Hover a name to trace it.
      </figcaption>
    </figure>
  );
}

/**
 * Who AI trusts in this category: the sites it cited in buyer answers, and which brands each one sat
 * beside. The ranked list of sites cited beside rivals but never beside the brand comes first; the
 * map and the full list of cited sites are one tap away. Replaces the plain cited-sites table.
 */
function CitationNetwork({ run }: { run: Run }) {
  const s = run.insights?.sources;
  const [open] = useState(() => !window.matchMedia(PHONE).matches);
  if (!s) return null;
  const brand = run.profile.name;
  const sample = run.mode !== "live_api"
    && <>{SAMPLE_NOTE} Every example.com address is a fictional placeholder. </>;
  if (s.reason) {
    return <Block open={open} className="finding" title="No cited sources to map" found={null}>
      <p className="muted" style={{ margin: 0 }}>{s.reason}</p>
    </Block>;
  }
  const by = new Map(s.sources.map((r) => [r.domain, r]));
  const gaps = (s.rival_only ?? []).map((d) => by.get(d)!).filter(Boolean);
  const names = probeLabels(run.probes, run.topics);
  const title = gaps.length
    ? `AI cited ${plural(gaps.length, "site")} beside your rivals, never beside ${brand}`
    : s.sources.some((r) => r.rivals?.length && r.kind !== "owned" && r.kind !== "rival")
      ? `Every third-party site AI cited beside a rival was cited beside ${brand} too`
      : `AI cited ${plural(s.sources.length, "site")}, no third-party site beside a rival`;
  const gapRow = (r: Source, i: number) => <GapSource key={r.domain} r={r} rank={i + 1} run={run} names={names} />;
  return (
    <Block open={open} className="finding" title={<>{title} <Term k="rival_only" icon /></>} found={null}>
      <p className="muted" style={{ margin: 0 }}>
        {sample}
        {gaps.length
          ? <>These were cited in buyer answers that named a rival and never mentioned {brand}: the pages
             to get onto. Tap one for the answers.</>
          : <>A site cited beside rivals but never beside {brand} would be listed here as a page to get onto.</>}
        {" "}A citation shows what the model read, not why it answered as it did.
      </p>
      {gaps.length > 0 && <div className="src-list">{gaps.slice(0, SHOWN_GAPS).map(gapRow)}</div>}
      {gaps.length > SHOWN_GAPS && (
        <details className="more">
          <summary className="muted">Show {plural(gaps.length - SHOWN_GAPS, "more site")}</summary>
          <div className="src-list">{gaps.slice(SHOWN_GAPS).map((r, i) => gapRow(r, i + SHOWN_GAPS))}</div>
        </details>
      )}
      <CitationMap run={run} sources={s.sources} gaps={new Set(gaps.map((r) => r.domain))} />
      <details className="more">
        <summary className="muted">
          All {plural(s.sources.length, "cited site")} · cited in {s.cited_answers} of {s.answers} buyer and brand answers
        </summary>
        <table className="named">
          <thead>
            <tr><th>Site</th><th>Answers</th><th>Cited beside</th></tr>
          </thead>
          <tbody>
            {s.sources.map((r) => (
              <tr key={r.domain}>
                <td><strong>{r.domain}</strong><br /><span className="muted">{r.rival ? `${r.rival}'s site` : KIND_LABEL[r.kind] ?? "other site"}</span></td>
                <td>{r.answers}<br /><span className="muted">{r.buyer} buyer · {r.brand} brand</span></td>
                <td className="muted">
                  {[...(r.with_brand ? [`${brand} (${r.with_brand})`] : []),
                    ...(r.rivals ?? []).map((x) => `${x.name} (${x.count})`)].join(", ") || "no brand named"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </Block>
  );
}

const SOURCE = { autocomplete: "Google", reddit: "Reddit" } as const;

/** "real demand · Google": the question is a real search; the popover lists its group's phrasings. */
function DemandBadge({ d }: { d: Demand }) {
  const n = d.phrasings.length;
  return (
    // inside a <summary>: a tap on the badge opens the popover, not the answer
    <span className="demand" onClick={(e) => e.preventDefault()}>
      <Popover label="Real demand" className="demand-badge" trigger={<>real demand · {SOURCE[d.source]}</>}>
        <strong className="pop-title">{GLOSSARY.real_demand.term}</strong>
        <p>
          People {d.source === "reddit" ? "ask exactly this on Reddit" : "search exactly this on Google"}.
        </p>
        {n > 1 && (
          <>
            <p className="muted">{n} real searches that mean the same, grouped together:</p>
            <ul className="demand-list">
              {d.phrasings.map((ph) => <li key={ph.text}>{ph.text} <span className="muted">· {SOURCE[ph.source]}</span></li>)}
            </ul>
          </>
        )}
        <p className="muted">This shows the question is real, not how often it is searched.</p>
      </Popover>
    </span>
  );
}

/** A cited page without its scheme, "www." or trailing slash. */
const page = (u: string) => u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");

/** Searches as “a”, “b” and “c”. */
const quoted = (qs: string[]) => qs.map((q, i) => (
  <span key={i}>{i ? (i === qs.length - 1 ? " and " : ", ") : ""}“{q}”</span>
));

/** Who ran the searches: the measured model through its API, by name when the answers record it. */
const searcher = (run: Run) => modelsOf(run).answered || "the AI";

/** One try in one sentence: what the model searched, how many pages it cited, and whether any was yours. */
function tryStory(t: SearchTry, who: string) {
  const own = t.owned_pages.length;
  return (
    <>
      {t.searches.length ? <>{who} searched {quoted(t.searches)}</> : `${who} answered without searching`}
      {t.pages.length ? ` and cited ${plural(t.pages.length, "page")}. ` : " and cited no pages."}
      {t.pages.length > 0 && (own ? <strong className="own">{own} {own === 1 ? "was" : "were"} yours.</strong> : "None was yours.")}
    </>
  );
}

const answeredOk = (run: Run, p: Probe) =>
  [run.answers, run.repeat_answers ?? []].flat().some((a) => a.probe_id === p.id && a.status === "ok");

/** What the model searched for one buyer question, every try, or that it was not recorded. */
function Searched({ run, p }: { run: Run; p: Probe }) {
  const s = run.insights?.searches;
  const tries = s?.questions[p.id];
  if (!s || p.phase !== "baseline" || (!tries && !answeredOk(run, p))) return null;
  return (
    <div className="searched">
      <h4>What the AI searched <Term k="fan_out" icon /></h4>
      {tries ? tries.map((t) => (
        <p key={t.try_no}>
          {run.mode !== "live_api" && <span className="tag sample">sample</span>}
          {tries.length > 1 && <strong>Try {t.try_no}: </strong>}{tryStory(t, searcher(run).replace(/^the/, "The"))}
        </p>
      )) : <p className="muted">Not recorded for this run.</p>}
    </div>
  );
}

/** The buyer questions in the three groups the report uses: where AI places you, where you aim to
 * be, and the questions asked for your own claims. */
function buyerGroups(run: Run): { title: ReactNode; probes: Probe[] }[] {
  const topics = new Map(run.topics.map((t) => [t.id, t]));
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  const front = (p: Probe) => topics.get(p.topic_id)?.front ?? null;
  const label = (f: string) => topics.get(buyer.find((p) => front(p) === f)?.topic_id ?? "")?.label ?? "";
  const groups: { title: ReactNode; probes: Probe[] }[] = [];
  const placed = buyer.filter((p) => front(p) === "placed" || front(p) === "both");
  const aiming = buyer.filter((p) => front(p) === "aiming");
  if (placed.length) groups.push({ title: <><Term k="where_placed">Where AI places you</Term>: {label(front(placed[0])!)}</>, probes: placed });
  if (aiming.length) groups.push({ title: <><Term k="where_aiming">Where you aim to be</Term>: {label("aiming")}</>, probes: aiming });
  const rest = buyer.filter((p) => !placed.includes(p) && !aiming.includes(p));
  if (rest.length) groups.push({ title: "Your claims", probes: rest });
  return groups;
}

/**
 * The model's own web searches for the buyer questions, grouped by the question they came from: does
 * any answer to it cite a page of yours? One question opens to its searches; the flat list of every
 * search, near-duplicates grouped, is one click away.
 */
function WhatItSearched({ run }: { run: Run }) {
  const [flat, setFlat] = useState(false);
  const s = run.insights?.searches;
  if (!s) return null;
  const replay = run.mode !== "live_api";
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  // The story: a question whose answer cited pages, none of them yours, preferring one that did not
  // name you either; else the first with searches.
  const first = (p: Probe) => s.questions[p.id]?.[0];
  const missed = buyer.filter((p) => first(p)?.pages.length && !first(p)!.owned_pages.length);
  const story = missed.find((p) => run.evaluations.find((e) => e.probe_id === p.id)?.mentioned === false)
    ?? missed[0] ?? buyer.find((p) => first(p)?.searches.length);
  const found = s.reason ? (s.answers ? "no web searches" : buyer.some((p) => answeredOk(run, p)) ? "not recorded" : "no buyer answers") : `${searcher(run)} ran ${plural(s.searches.length, "different search", "different searches")};`
    + ` your site was cited after ${s.owned ? s.owned : "none"} of them`;
  return (
    <Section title="What the AI searched" found={found}>
      {s.reason ? <p className="muted" style={{ margin: 0 }}>{s.reason}</p> : (
        <>
          <p style={{ margin: 0 }}>
            {replay && <>{SAMPLE_NOTE} The searches were written by hand too. </>}
            To answer a buyer, the AI first runs a few <Term k="fan_out">web searches</Term> of its own.
            A search that never leads to your site is where you go missing. Open a question for its searches.
          </p>
          {story && (
            <p className="callout story-line">
              {replay && <span className="tag sample">sample</span>}
              When a buyer asked “{story.text}”, {tryStory(first(story)!, searcher(run))}
            </p>
          )}
          {!flat ? (
            <div className="table-scroll">
              <table className="compact">
                <thead><tr><th>Buyer question</th><th className="num">Searches</th><th>Cited your site?</th></tr></thead>
                {buyerGroups(run).map((g, gi) => (
                  <tbody key={gi}>
                    <tr className="grp"><td colSpan={3}>{g.title} · {g.probes.filter((p) => cited(s.questions[p.id]) === true).length} of {plural(g.probes.length, "question")} cited you</td></tr>
                    {g.probes.map((p) => {
                      const tries = s.questions[p.id] ?? [];
                      const searches = [...new Set(tries.flatMap((t) => t.searches))];
                      const pages = [...new Set(tries.flatMap((t) => t.pages))];
                      const yours = cited(tries);
                      return (
                        <tr key={p.id}>
                          <td>
                            <details className="qsearches">
                              <summary>{p.text}</summary>
                              <div className="chips">{searches.map((q) => <span key={q} className="chip-q">{q}</span>)}</div>
                              <p className="muted" style={{ margin: ".3rem 0 0" }}>
                                {plural(pages.length, "page")} cited{yours ? `, ${plural(new Set(tries.flatMap((t) => t.owned_pages)).size, "of them", "of them")} yours` : ", none yours"} · <QRef id={p.id} run={run} />
                              </p>
                            </details>
                          </td>
                          <td className="num">{searches.length}</td>
                          <td>{yours == null ? <span className="muted">not recorded</span> : yours ? <span className="ok">Yes</span> : "No"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                ))}
              </table>
            </div>
          ) : (
            <ul className="search-list">
              {s.searches.map((g) => (
                <li key={g.query}>
                  <Popover wide label={`Search: ${g.query}`} className="search-row"
                           trigger={<>
                             <span className="search-q">“{g.query}”</span>
                             <span className="chip-count">{plural(g.answers, "answer")}</span>
                             {g.owned_pages.length ? <span className="pill landed">your site</span>
                               : <span className="pill neutral">not you</span>}
                           </>}>
                    <strong className="pop-title">“{g.query}”</strong>
                    {g.variants.length > 0 && (
                      <p className="muted">Also searched as {quoted(g.variants)}: the same search with another year or spelling.</p>
                    )}
                    <h4>Came from</h4>
                    <p>{refs(g.questions, run)} · run in {plural(g.answers, "answer")}</p>
                    <h4>Pages cited in {g.answers === 1 ? "that answer" : "those answers"}</h4>
                    {g.pages.length ? (
                      <ul className="page-list">
                        {g.pages.map((u) => (
                          <li key={u}>{page(u)}{g.owned_pages.includes(u) && <> <span className="pill landed">your site</span></>}</li>
                        ))}
                      </ul>
                    ) : <p className="muted">None.</p>}
                    <p className="muted">
                      The AI does not say which search found which page, so this lists every page{" "}
                      {g.answers === 1 ? "that answer" : "those answers"} cited
                      {replay && ". Every example.com address is a fictional placeholder"}.
                    </p>
                  </Popover>
                </li>
              ))}
            </ul>
          )}
          <p style={{ margin: 0 }}>
            <button type="button" className="linky" onClick={() => setFlat((f) => !f)}>
              {flat ? "Group the searches by buyer question" : `Show all ${plural(s.searches.length, "search", "searches")} as one list`}
            </button>
          </p>
        </>
      )}
    </Section>
  );
}

/** Whether any try of a question cited a page of yours; null when nothing was recorded for it. */
const cited = (tries?: SearchTry[]) => (tries?.length ? tries.some((t) => t.owned_pages.length > 0) : null);

const score = (x: number) => x.toFixed(2);
const behind = (r: RetrievalRow) => !!(r.yours && r.rival && r.rival.score > r.yours.score);

/** The one gap a fix does the most for: the question where the rewrite lifts your score the most. */
function biggestFix(run: Run): RetrievalRow | undefined {
  const lift = (r: RetrievalRow) => (r.fixed && r.yours ? r.fixed.score - r.yours.score : -1);
  return (run.retrieval?.rows ?? []).filter((r) => behind(r) && lift(r) > 0).sort((a, b) => lift(b) - lift(a))[0];
}

/** A passage in place: its page, the words, and which search it matched best. */
function PassageQuote({ title, p }: { title: string; p: ScoredPassage }) {
  return (
    <>
      <h4>{title} · {score(p.score)}</h4>
      <p className="muted" style={{ margin: 0 }}>{page(p.url)} · closest to “{p.query}”</p>
      <p className="quote">{p.text}</p>
    </>
  );
}

/** Ask the model once more with the rewritten passage and the cited page as its only sources. */
function Reask({ run, r, got, onReasked }: {
  run: Run; r: RetrievalRow; got: RetrievalRow["reask"];
  onReasked: (probe: string, got: RetrievalRow["reask"]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (run.mode !== "live_api" || !r.fixed) return null;
  const ask = () => {
    setBusy(true); setError(null);
    reaskRun(run.id, r.probe_id)
      .then((next) => onReasked(r.probe_id, next.retrieval?.rows.find((x) => x.probe_id === r.probe_id)?.reask ?? null))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <div className="reask">
      {got ? (
        <p style={{ margin: 0 }}>
          <span className="tag sample">quick check, not proof</span>{" "}
          Handed the rewritten passage and the cited page as its only sources, {got.model}{" "}
          {got.named ? <strong className="own">named {run.profile.name}.</strong> : <strong>still did not name {run.profile.name}.</strong>}
        </p>
      ) : (
        <button type="button" className="primary" disabled={busy} onClick={ask}>
          {busy ? "Asking…" : "Quick check: 1 ask, not proof"}
        </button>
      )}
      <p className="muted" style={{ margin: 0 }}>
        {got ? "One ask, not a measurement: it changes no number." : "One model call on your pass. A simulation: the AI is handed both passages as its only sources, so it shows whether the rewrite would be used, not whether a real search finds it."}
      </p>
      {error && <div className="callout error">{error}</div>}
    </div>
  );
}

/** A retrieval row's result in words: how the rewrite moved your match, else how you compare. */
function fixResult(r: RetrievalRow): { text: string; tone: string } {
  if (r.fixed && r.yours) {
    const d = moved(r.yours.score, r.fixed.score);
    if (r.rival && r.fixed.score >= r.rival.score) return { text: "Rewrite matches as well as the cited page", tone: "ok" };
    return d >= MATCH_STEP ? { text: "Rewrite: closer", tone: "ok" } : d <= -MATCH_STEP ? { text: "Rewrite: worse", tone: "worse" }
      : { text: "Rewrite: no change", tone: "muted" };
  }
  if (!r.rival || !r.yours) return { text: "No cited page to compare", tone: "muted" };
  return behind(r) ? { text: "Cited page matches better", tone: "muted" } : { text: "You match better", tone: "ok" };
}

const SHOWN_FIX_ROWS = 8;

/**
 * Test a fix: per buyer question, your best passage against the best passage of a page AI cited,
 * and yours again with the win-back rewrite in the page. Similarity only, labelled as a simulation.
 * One table, rows with a suggested fix first; a question opens its passages and the quick check.
 */
function TestAFix({ run, reasks, onReasked }: {
  run: Run; reasks: Record<string, RetrievalRow["reask"]>;
  onReasked: (probe: string, got: RetrievalRow["reask"]) => void;
}) {
  const [all, setAll] = useState(false);
  const sim = run.retrieval;
  if (!sim) return null;
  const replay = sim.provenance !== "live_api";
  const probes = new Map(run.probes.map((p) => [p.id, p]));
  const fixes = new Map((run.win_back ?? []).map((a) => [a.attribute_id, a]));
  const compared = sim.rows.filter((r) => r.yours && r.rival);
  const weaker = compared.filter(behind).length;
  const found = compared.length
    ? `Your best page is weaker than the page AI cited for ${weaker} of ${plural(compared.length, "unbranded question")}`
    : "no page AI cited could be compared";
  const rows = [...sim.rows].sort((a, b) => Number(!!b.fixed) - Number(!!a.fixed) || Number(behind(b)) - Number(behind(a)));
  const shown = all ? rows : rows.slice(0, SHOWN_FIX_ROWS);
  const num = (p: ScoredPassage | null) => (p ? score(p.score) : "–");
  return (
    <Section title="Test a fix" found={found}>
      <p style={{ margin: 0 }}>
        {replay && <>Authored sample, not computed: the passages and scores were written by hand to show this panel. </>}
        A <Term k="retrieval_score">retrieval score</Term> from 0 to 1: how closely a passage of a page matches the
        question and the AI's searches for it. We scored your pages, the pages AI cited, and your page with the
        suggested rewrite from Quick wins in it. A simulation of what the AI reads first, not a promise of a citation.
        Open a question for the passages.
      </p>
      <div className="table-scroll">
        <table className="compact">
          <thead><tr><th>Buyer question</th><th className="num">You</th><th className="num">Page AI cited</th>
            <th className="num">With the fix</th><th>Result</th></tr></thead>
          <tbody>
            {shown.map((r) => {
              const p = probes.get(r.probe_id);
              const fix = r.fix_attribute_id ? fixes.get(r.fix_attribute_id) : undefined;
              const res = fixResult(r);
              return (
                <tr key={r.probe_id}>
                  <td>
                    <Popover wide label={`Passages for: ${p?.text ?? r.probe_id}`} className="linky row-open" trigger={p?.text ?? r.probe_id}>
                      <strong className="pop-title">{p?.text}</strong>
                      {replay && <p><span className="tag sample">sample</span> Written by hand; example.com pages are fictional.</p>}
                      {r.yours ? <PassageQuote title="Your best passage" p={r.yours} /> : <p className="muted">None of your pages could be read.</p>}
                      {r.rival ? <PassageQuote title="Best passage of a page AI cited" p={r.rival} />
                        : <p className="muted">No page AI cited for this question could be read.</p>}
                      {r.fixed ? (
                        <>
                          <PassageQuote title={`With the fix${fix ? ` for “${fix.label}”` : ""}`} p={r.fixed} />
                          <p className="muted" style={{ margin: 0 }}>
                            {r.rival && r.fixed.score >= r.rival.score ? "The rewrite now matches this question at least as closely as the page AI cited."
                              : r.yours && r.fixed.score > r.yours.score ? "The rewrite closes part of the gap."
                              : "The rewrite does not match this question more closely than your page already does."}
                          </p>
                          <Reask run={run} r={r} got={r.reask ?? reasks[`${run.id}:${r.probe_id}`]} onReasked={onReasked} />
                        </>
                      ) : <p className="muted">No suggested fix targets this question.</p>}
                      <p className="muted">Scored against {plural(r.queries, "search", "searches")}: the question and the AI's own searches for it; the best match counts.</p>
                    </Popover>
                  </td>
                  <td className="num">{num(r.yours)}</td>
                  <td className="num">{num(r.rival)}</td>
                  <td className="num">{num(r.fixed)}</td>
                  <td className={res.tone}>{res.text}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > SHOWN_FIX_ROWS && (
        <p style={{ margin: 0 }}><button type="button" className="linky" onClick={() => setAll((x) => !x)}>
          {all ? "Show fewer" : `Show ${plural(rows.length - SHOWN_FIX_ROWS, "more question")}`}
        </button></p>
      )}
      {sim.skipped.length > 0 && (
        <details className="skipped">
          <summary className="muted">What we could not read ({sim.skipped.length})</summary>
          <ul>{sim.skipped.map((x, i) => <li key={i} className="muted">{x}</li>)}</ul>
        </details>
      )}
      {!replay && <p className="muted" style={{ margin: 0 }}>{plural(sim.passages, "passage")} from {plural(sim.pages, "page")}, scored with {sim.model}.</p>}
    </Section>
  );
}

/** Overview's one line on the gap a suggested fix does the most for. */
function FixLine({ run, onOpen }: { run: Run; onOpen: () => void }) {
  const r = biggestFix(run);
  if (!r?.yours || !r.rival || !r.fixed) return null;
  const q = run.probes.find((p) => p.id === r.probe_id);
  return (
    <p className="callout story-line">
      {run.retrieval?.provenance !== "live_api" && <span className="tag sample">sample</span>}{" "}
      <strong>Biggest fixable gap:</strong> for “{q?.text}”, your best page scores {score(r.yours.score)} and
      the page AI cited {score(r.rival.score)}. With the suggested rewrite yours scores {score(r.fixed.score)}{" "}
      (<Term k="retrieval_score">simulated</Term>).{" "}
      <button type="button" className="pop-trigger linky" onClick={onOpen}>Test a fix</button>
    </p>
  );
}

/** One question as a compact row; opening it shows the full answer and what the scorer made of it. */
function QuestionRow({ p, name, answer, verdict, tags, note, replay, after, sub }: {
  p: Probe; name: string; answer?: Answer; verdict?: ReactNode; tags?: ReactNode; note?: ReactNode;
  replay: boolean; after?: ReactNode; sub?: ReactNode;
}) {
  return (
    <details className="qrow">
      <summary>
        <span className="muted qrow-name" title={p.id}>{name}{sub && <> · {sub}</>}</span>
        <span className="qrow-text">{p.text}{p.demand && <DemandBadge d={p.demand} />}</span>
        {verdict}
      </summary>
      <div className="qrow-body">
        {tags && <div className="row" style={{ flexWrap: "wrap", gap: ".3rem" }}>{tags}</div>}
        {note}
        <p className="muted long-answer">
          {answer && replay && <span className="tag sample">sample</span>}
          {answer ? plain(answer.text) : "no answer"}
        </p>
        <WhatItRead a={answer} />
        {after}
      </div>
    </details>
  );
}

/** Buyer questions never name the company: did AI bring it up on its own? */
function BuyerQuestions({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const d = run.drift;
  const brand = run.profile.name;
  const names = probeLabels(run.probes, run.topics);
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const evals = new Map(run.evaluations.map((e) => [e.probe_id, e]));
  const base = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  const follow = run.probes.filter((p) => p.kind === "blind" && p.phase === "followup");
  const control = run.probes.find((p) => p.phase === "control");
  const realAsked = base.filter((p) => p.demand).length;
  const tries = d?.tries ?? 1;
  // Every try of one question, first try first: [answer, evaluation] pairs.
  const repeatAnswers = new Map((run.repeat_answers ?? []).map((a) => [`${a.probe_id}#${a.try_no}`, a]));
  const triesOf = (p: Probe) => [
    [answers.get(p.id), evals.get(p.id)] as const,
    ...(run.repeat_evaluations ?? []).filter((e) => e.probe_id === p.id)
      .sort((x, y) => (x.try_no ?? 1) - (y.try_no ?? 1))
      .map((e) => [repeatAnswers.get(`${p.id}#${e.try_no}`), e] as const),
  ];
  const countedTries = (p: Probe) => triesOf(p)
    .filter(([a, e]) => a && e && counts(a, e)).map(([, e]) => e!);
  const counted = (p: Probe) => {
    const a = answers.get(p.id), e = evals.get(p.id);
    return a && e && counts(a, e) ? e : null;
  };
  const all = base.flatMap(countedTries);
  const namedIn = all.filter((e) => e.mentioned).length;
  const recIn = all.filter((e) => e.recommended).length;
  // only the repeat-sampled questions have more than one try, so the total is asks, not questions x tries
  const asks = base.reduce((n, p) => n + triesOf(p).length, 0);
  const excluded = asks - all.length;
  const sampled = base.filter((p) => triesOf(p).length > 1).length;
  const verdict = (p: Probe) => {
    if (triesOf(p).length > 1) {
      const got = countedTries(p), k = got.filter((e) => e.mentioned).length;
      if (!got.length) return <span className="tag warn">excluded from scores</span>;
      const tone = k === 0 ? "lost_claim" : k === got.length ? "landed" : "unprioritised";
      return <span className={`pill ${tone}`}>named in {k} of {got.length} tries</span>;
    }
    const e = counted(p);
    if (!e) return <span className="tag warn">excluded from scores</span>;
    if (e.recommended) return <span className="pill landed">recommended you</span>;
    if (e.negative_mention) return <span className="pill contested">criticised you</span>;
    if (e.mentioned) return <span className="pill unprioritised">named you</span>;
    return <span className="pill lost_claim">did not name you yet</span>;
  };
  const tryWord = (a?: Answer, e?: QueryEvaluation) =>
    !a || !e || !counts(a, e) ? "excluded" : e.recommended ? "recommended you" : e.mentioned ? "named you" : "did not name you";
  // who AI named in the answer, on the card itself: the rival a buyer was shown instead
  const others = (p: Probe) => {
    const e = evals.get(p.id), named = e?.competitor_recommendations ?? [];
    return named.length ? `${e!.mentioned ? "also named" : "named instead"}: ${named.slice(0, 3).join(", ")}`
      + (named.length > 3 ? ` +${named.length - 3}` : "") : undefined;
  };
  const card = (p: Probe) => {
    const shown = triesOf(p);
    return (
      <QuestionRow key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)}
                   verdict={verdict(p)} replay={replay} sub={others(p)}
                   note={<>
                     {evals.get(p.id)?.explanation && <span className="muted">{evals.get(p.id)!.explanation}</span>}
                     <Searched run={run} p={p} />
                     {shown.length > 1 && (
                       <span className="muted">
                         {shown.map(([a, e], i) => `Try ${i + 1}: ${tryWord(a, e)}`).join(" · ")}. Every try’s answer is below.
                       </span>
                     )}
                   </>}
                   after={shown.slice(1).map(([a], i) => (
                     <p key={i} className="muted long-answer">
                       <strong>Try {i + 2}:</strong> {a ? plain(a.text) : "no answer"}
                     </p>
                   ))} />
    );
  };
  const vis = d?.visibility;
  // Grouped by front when the run has labelled ones; one unlabelled set otherwise, as replay has.
  const topicFront = new Map(run.topics.map((t) => [t.id, t.front ?? null]));
  const fronts = d ? frontsOf(d) : [];
  const probeById = new Map(run.probes.map((p) => [p.id, p]));
  return (
    <Section className="qset" title={<Term k="buyer_question">Unbranded questions</Term>}
               found={!base.length ? na(d?.na_reasons, "visibility")
                 : `${plural(base.length, "question")} asked once`
                   + (sampled ? `, ${sampled} of them ${tries} times over` : "")
                   + ` · named you in ${namedIn} of ${all.length} answers${recIn ? ` · recommended you in ${recIn}` : ""}`
                   + (excluded ? ` · ${excluded} excluded` : "")}>
        <details className="qhow">
        <summary>How these were asked ⓘ</summary>
        <p className="muted" style={{ margin: 0 }}>
          What a buyer would ask without naming {brand}. Each one AI answered without
          bringing {brand} up is room to be found.
          {fronts.length > 1 && ` They are asked on two fronts, half each: the category AI’s brand answers`
            + ` already place ${brand} in, and the category its own site aims for.`}
          {sampled > 0
            ? ` The model answers differently each time, so`
              + ` ${plural(sampled, "of these questions was", "of these questions were")} asked ${tries} times`
              + ` over in a fresh context, to show how much one question wobbles. Every question counts once`
              + ` towards the score however often it was asked: the budget goes on asking more different`
              + ` questions, which is what narrows the range.`
            : replay ? " A sample run replays one authored answer per question: 1 try." : " Each was asked once."}
        </p>
        <SamplerNote run={run} />
        {(realAsked > 0 || !!run.demand_notes?.length) && (
          <p style={{ margin: 0 }}>
            {realAsked ? `${realAsked} of ${base.length} are ` : "None of them are "}
            <Term k="real_demand" note={run.demand_notes?.join(" ")}>real searches</Term>
            {realAsked ? (realAsked < base.length ? "; AI wrote the rest." : ".") : ": AI wrote them all."}
          </p>
        )}
        {fronts.length > 0 && d && gapSentence(d, brand) && <p style={{ margin: 0 }}>{gapSentence(d, brand)}<GapVerdict d={d} /></p>}
        </details>
        {!fronts.length && vis != null && (
          <p style={{ margin: 0 }}>
            <strong>Buyer visibility <Visibility d={d!} explain /></strong>{" "}
            <span className="muted">— <Range d={d!} iv={d!.visibility_interval} note={d!.na_reasons?.visibility_interval} /></span>
          </p>
        )}
        {!fronts.length && d?.low_confidence && (
          <p className="warn" style={{ margin: 0 }}>{d.low_confidence} The control question is below the questions.</p>
        )}
        {!control && run.mode === "live_api" && !run.profile.core_category && (
          <p className="warn" style={{ margin: 0 }}>
            No <Term k="core_category">core category</Term> was saved for {brand}, so where it aims to be was not asked
            about. Set the category on the claims screen and measure again.
          </p>
        )}
        {fronts.length ? fronts.map((v) => {
          const ps = base.filter((p) => topicFront.get(p.topic_id) === v.front);
          const ctl = v.control_probe_id ? probeById.get(v.control_probe_id) : undefined;
          return (
            <div className="front-group" key={v.front}>
              <h4 style={{ margin: ".4rem 0 0" }}>
                <FrontLabel v={v} /> · {v.category} — <Visibility d={v} explain />{" "}
                <span className="muted">— <Range d={v} iv={v.interval} note={v.interval_note} /></span>
              </h4>
              {run.sampler && <p className="muted" style={{ margin: 0 }}><FrontMargin run={run} front={v.front} /></p>}
              <div className="qlist">{ps.map(card)}</div>
              {ctl && <Control run={run} p={ctl} v={v} />}
            </div>
          );
        }) : <div className="qlist">{base.map(card)}</div>}
        {fronts.length > 0 && base.some((p) => !topicFront.get(p.topic_id)) && (
          <div className="front-group">
            <h4 style={{ margin: ".4rem 0 0" }}>Your claims <span className="muted">— counted in neither front</span></h4>
            <div className="qlist">{base.filter((p) => !topicFront.get(p.topic_id)).map(card)}</div>
          </div>
        )}
        {follow.length > 0 && (
          <>
            <h4>Follow-up questions (exploratory — not counted in the scores)</h4>
            <div className="qlist">{follow.map(card)}</div>
          </>
        )}
      {!fronts.length && control && d && <Control run={run} p={control} v={d} />}
    </Section>
  );
}

/**
 * The control question of one set: can the answering model name the companies leading this category, and
 * does it count the brand among them? It is not a buyer question and never moves visibility; it only
 * says whether that set's number can be trusted.
 */
function Control({ run, p, v }: { run: Run; p: Probe; v: Vis }) {
  const a = run.answers.find((x) => x.probe_id === p.id);
  const e = run.evaluations.find((x) => x.probe_id === p.id);
  const flag = v.low_confidence;
  const ok = a && e && counts(a, e);
  const found = !ok ? "could not be scored"
    : `named ${plural(e.competitor_recommendations.length + (e.mentioned ? 1 : 0), "company", "companies")}`
      + ` · ${e.mentioned ? `including ${run.profile.name}` : `not ${run.profile.name}`}`;
  return (
    <Section title="Control question"
             found={flag ? <><Term k="low_confidence"><span className="tag warn">low confidence</span></Term> {found}</> : found}>
      <p className="muted" style={{ margin: 0 }}>
        One question asked beside the unbranded questions and never scored: does the answering model know
        who leads this category, and is {run.profile.name} among them? If not, this set’s buyer
        visibility is flagged low confidence.
      </p>
      {flag && <div className="callout warn-box" style={{ margin: 0 }}><strong>Low confidence.</strong> {flag}</div>}
      {!flag && ok && v.visibility === 0 && (
        <p style={{ margin: 0 }}>
          The model names {run.profile.name} among the companies leading this category, yet never brought it
          up for a buyer: the 0 is a finding, not a gap in what the model knows.
        </p>
      )}
      <div className="qlist">
        <QuestionRow p={p} name="Control question" answer={a} replay={run.mode !== "live_api"}
                     note={ok && e.competitor_recommendations.length > 0 && (
                       <span className="muted">Companies it named: {e.competitor_recommendations.join(", ")}</span>
                     )} />
      </div>
    </Section>
  );
}

/**
 * How to win it back: per claim to win back or amplify, the page to change, a suggested rewrite and
 * the buyer questions it should help with. The server kept only actions whose page was read and
 * whose questions were asked; a claim that became a target by re-scoring has no action yet.
 */
function winBackPlan(run: Run) {
  const targets = run.attribute_scores.filter((s) => !s.discovered && (s.zone === "lost_claim" || s.zone === "unstated_intent"));
  const zones = new Set(targets.map((s) => s.attribute_id));
  return { targets, actions: (run.win_back ?? []).filter((a) => zones.has(a.attribute_id)) };
}

/** What a rewrite changes on its page: a word diff when it replaces copy, else the new passage. The
 * heading is the buyer question the passage answers. */
function WhatChanges({ a }: { a: WinBackAction }) {
  const parts = a.current_copy ? wordDiff(a.current_copy, a.rewrite) : null;
  return (
    <div className="changes">
      <h4>What changes on <a href={a.page_url} target="_blank" rel="noreferrer">{shortPage(a.page_url)}</a></h4>
      {a.heading && <p className="diff-heading"><ins>{a.heading}</ins></p>}
      {parts ? (
        <p className="diff">
          {parts.map((d, i) => d.op === "same" ? <span key={i}>{d.text} </span>
            : d.op === "add" ? <ins key={i}>{d.text}</ins> : <del key={i}>{d.text}</del>).reduce<ReactNode[]>(
            (out, el, i) => (i ? [...out, " ", el] : [el]), [])}
        </p>
      ) : <p className="diff"><ins>{a.rewrite}</ins></p>}
      <p className="muted">
        {parts ? `${plural(wordsIn(parts, "add"), "word")} added, ${wordsIn(parts, "del")} removed`
          : "A new passage: nothing on the page is replaced"}
        {a.heading ? ", headed by the buyer's own question." : "."}
      </p>
    </div>
  );
}

const shortPage = (u: string) => u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");

/** Step ① as a table: per targeted question, today's best passage, the page AI cited, and with the
 * rewrite, from the retrieval simulation (the same scores as Why AI misses you → Test a fix). */
function MatchTable({ a, run }: { a: WinBackAction; run: Run }) {
  const rows = matchRows(a, run.retrieval?.rows ?? []);
  const cited = new Map((run.retrieval?.rows ?? []).map((r) => [r.probe_id, r.rival?.url]));
  if (!run.retrieval) return <p className="muted">No match scores for this run.</p>;
  return (
    <div className="table-scroll">
      <table className="compact">
        <thead><tr><th>Buyer question</th><th className="num">Today</th><th className="num">Page AI cited</th>
          <th className="num">With the rewrite</th><th>Change</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.probe_id}>
              <td><QRef id={r.probe_id} run={run} text /></td>
              <td className="num">{r.today?.toFixed(2) ?? "–"}</td>
              <td className="num">{r.cited != null
                ? <span title={cited.get(r.probe_id) ?? undefined}>{r.cited.toFixed(2)}</span> : "–"}</td>
              <td className="num">{r.fixed?.toFixed(2) ?? "–"}</td>
              <td>{r.change == null ? <span className="muted">not scored</span>
                : r.change >= MATCH_STEP ? <span className="ok">closer ({signed(r.change)})</span>
                : r.change <= -MATCH_STEP ? <span className="worse">worse ({signed(r.change)})</span>
                : <span className="muted">no change ({signed(r.change)})</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(2)}`;

const REPLAY_LABEL: Partial<Record<WhyVerdict["kind"], { label: string; tone: string }>> = {
  copy_fix: { label: "Proven", tone: "good" }, authority_fix: { label: "Proven once found", tone: "good" },
  not_movable: { label: "No change", tone: "caution" }, copy_lowers: { label: "Makes it worse", tone: "caution" },
  not_reproducible: { label: "Could not be tested", tone: "plain" }, undecided: { label: "Not decided", tone: "plain" },
  budget: { label: "Stopped at budget", tone: "plain" }, cancelled: { label: "Stopped", tone: "plain" },
  ceiling: { label: "Already at the top", tone: "plain" },
};

/** Step ② for one buyer question: its latest replay test, or the button that runs one. */
function ReplayTest({ run, a, probe, inv, budget, onDone }: {
  run: Run; a: WinBackAction; probe: string; inv?: Investigation; budget: number | null; onDone: (i: Investigation) => void;
}) {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);
  const verdict = inv?.verdicts.at(-1);
  const tag = verdict && REPLAY_LABEL[verdict.kind];
  const start = () => {
    setBusy(true); setError(null); setLog([]);
    stop.current = streamRewriteTest(run.id, a.attribute_id, probe, {
      onLog: (e) => setLog((l) => [...l, e.text]),
      onDone: (i) => { setBusy(false); onDone(i); },
      onError: (e) => { setBusy(false); setError(e.message); },
    });
  };
  return (
    <div className="replay">
      <QRef id={probe} run={run} text />
      {verdict ? (
        <p>{tag && <span className={`pill ${tag.tone}`}>{tag.label}</span>} {verdict.text}{" "}
          <span className="muted">({inv!.spent_usd.toFixed(2)} USD, replays with search off; {inv!.judge})</span></p>
      ) : run.mode === "live_api" ? (
        <button type="button" className="ghost" disabled={busy} onClick={start}>
          {busy ? "Testing…" : `Run replay test${budget != null ? ` (up to $${budget.toFixed(2)})` : ""}`}
        </button>
      ) : <p className="muted">A sample run cannot be tested: its answers were written by hand.</p>}
      {busy && log.length > 0 && <ol className="why-log" aria-live="polite">{log.map((l, i) => <li key={i}>{l}</li>)}</ol>}
      {error && <div className="callout error">{error}</div>}
    </div>
  );
}

/** Step ③: "Mark fix live" on a proven rewrite, once it is published. */
function LiveCheck({ inv, onChecked }: { inv?: Investigation; onChecked?: (v: Verification) => void }) {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const proven = inv && inv.verdicts.some((v) => v.fix === "copy" || v.fix === "authority");
  if (!inv || !proven) return <p className="muted">Once a replay test proves the rewrite, publish it, then check it here.</p>;
  const v = inv.verification;
  const run = () => {
    setBusy(true); setError(null); setLog([]);
    streamRecheck(inv.id, {
      onLog: (e) => setLog((l) => [...l, e.text]),
      onDone: (x) => { setBusy(false); onChecked?.(x); },
      onError: (e) => { setBusy(false); setError(e.message); },
    });
  };
  return (
    <div className="replay">
      {v && <p><strong>{v.verdict.replace(/_/g, " ")}:</strong> {v.text}</p>}
      <button type="button" className="ghost" disabled={busy} onClick={run}>
        {busy ? "Checking…" : v ? "Check again" : "Mark fix live"}
      </button>
      <span className="muted"> The page is read first, free; only a published fix is asked about live.</span>
      {busy && log.length > 0 && <ol className="why-log" aria-live="polite">{log.map((l, i) => <li key={i}>{l}</li>)}</ol>}
      {error && <div className="callout error">{error}</div>}
    </div>
  );
}

/** One rewrite's verdict line, from the strongest evidence there is: live, replay, then the match check. */
function rewriteVerdict(match: MatchVerdict, tests: Investigation[]): { text: string; tone: string } {
  const kinds = tests.map((t) => t.verdicts.at(-1)?.kind);
  const does = (t: Investigation) => (t.counts === "recommends" ? "recommends" : "names");
  const confirmed = tests.find((t) => t.verification?.verdict === "confirmed");
  if (confirmed) return { text: `Confirmed live: AI now ${does(confirmed)} you for it.`, tone: "good" };
  if (kinds.some((k) => k === "copy_fix" || k === "authority_fix")) return { text: "Proven in replay: publish it, then mark it live.", tone: "good" };
  const lowers = tests.find((t) => t.verdicts.at(-1)?.kind === "copy_lowers");
  if (lowers) return { text: `Disproven: in replay it makes AI ${does(lowers) === "recommends" ? "recommend" : "name"} you less. Don't publish it.`, tone: "caution" };
  const moved = kinds.filter((k) => k !== "ceiling");
  if (moved.length && moved.every((k) => k === "not_movable")) return { text: "Disproven: in replay it changes nothing. Don't publish it as is.", tone: "caution" };
  if (tests.length && !moved.length) return { text: `Already at the top: in replay AI already ${does(tests[0])} you for ${tests.length === 1 ? "this question" : "these questions"}, so no rewrite can show a gain.`, tone: "plain" };
  if (match === "worse") return { text: "Don't publish: it matches the buyer questions worse than today's copy.", tone: "caution" };
  return { text: "Not proven yet: run a replay test before publishing.", tone: "plain" };
}

/** One rewrite as a ranked row: a one-line summary, then what changes, why, and its proof. */
function RewriteRow({ a, rank, run, invs, budget, onInv }: {
  a: WinBackAction; rank: number | null; run: Run; invs: Investigation[]; budget: number | null;
  onInv: (i: Investigation) => void;
}) {
  const rows = matchRows(a, run.retrieval?.rows ?? []);
  const m = matchVerdict(rows);
  const tests = a.question_ids.map((q) => latestTest(invs, a.attribute_id, q)).filter(Boolean) as Investigation[];
  const verdict = rewriteVerdict(m.verdict, tests);
  const score = run.attribute_scores.find((s) => s.attribute_id === a.attribute_id);
  const one = rows.length === 1 && rows[0].change != null;
  return (
    <li>
      <details open={rank === 1}>
        <summary>
          <span className="rank">{rank ?? "–"}</span>
          <span className="r-title">{a.label}</span>
          <span className="chev" aria-hidden="true">▸</span>
          <span className="r-meta">
            <span className={`pill ${m.verdict === "worse" ? "caution" : m.verdict === "closer" ? "good" : "plain"}`}>
              {one ? `Match ${rows[0].today?.toFixed(2)} → ${rows[0].fixed?.toFixed(2)}`
                : m.verdict === "not_scored" ? "Match not scored"
                : `Match: closer on ${m.closer} of ${m.scored}, worse on ${m.worse}`}
            </span>
            <span className={`pill ${tests.length ? verdict.tone : "plain"}`}>{tests.length ? `Replay: ${tests.length} of ${a.question_ids.length} tested` : "Replay: not tested"}</span>
            <span>{plural(a.question_ids.length, "buyer question")}</span>
          </span>
        </summary>
        <div className="x-body">
          <WhatChanges a={a} />
          <div>
            <h4>Why this rewrite</h4>
            <p>{a.why || "No reason was given."}</p>
          </div>
          <div className="proof">
            <h4>Proof</h4>
            <ol className="ladder">
              <li className={m.verdict === "worse" ? "bad-step" : ""}>
                <strong>① <Term k="retrieval_score">Match check</Term></strong> <span className="muted">free, already done</span>
                <MatchTable a={a} run={run} />
              </li>
              <li>
                <strong>② <Term k="replay_test">Replay test</Term></strong> <span className="muted">before you publish</span>
                {a.question_ids.map((q) => (
                  <ReplayTest key={q} run={run} a={a} probe={q} inv={latestTest(invs, a.attribute_id, q)} budget={budget}
                              onDone={onInv} />
                ))}
              </li>
              <li>
                <strong>③ <Term k="fix_recheck">Live check</Term></strong> <span className="muted">after you publish</span>
                {tests.filter((t) => t.verdicts.some((v) => v.fix === "copy" || v.fix === "authority")).map((t) => (
                  <LiveCheck key={t.id} inv={t} onChecked={(v) => onInv({ ...t, verification: v })} />
                ))}
                {!tests.some((t) => t.verdicts.some((v) => v.fix === "copy" || v.fix === "authority")) && <LiveCheck />}
              </li>
            </ol>
          </div>
          <p className={`verdict-line ${verdict.tone}`}><strong>Verdict:</strong> {verdict.text}</p>
          {score && <div><Popover wide label={a.label} className="linky" trigger="All evidence"><ClaimDetail s={score} run={run} /></Popover></div>}
        </div>
      </details>
    </li>
  );
}

const latestTest = (invs: Investigation[], attribute: string, probe: string) =>
  invs.filter((i) => i.kind === "buyer" && i.attribute_id === attribute && i.probe_id === probe)
    .sort((x, y) => y.created_at.localeCompare(x.created_at))[0];

/** A fix inside a claim's popover: the rewrite and where it goes, briefly. The proof lives on Quick wins. */
function FixCard({ a, run }: { a: WinBackAction; run: Run }) {
  const zone = run.attribute_scores.find((s) => s.attribute_id === a.attribute_id)?.zone ?? a.zone;
  return (
    <div className="question">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <strong>{a.label}</strong>
        <span className={`pill ${zone}`}>{ZONE_LABEL[zone]}</span>
      </div>
      {run.mode !== "live_api" && <span className="tag sample">sample</span>}
      <WhatChanges a={a} />
      {a.question_ids.length ? <p className="muted" style={{ margin: 0 }}>For {refs(a.question_ids, run)}.</p>
        : <span className="muted">No unbranded question in this run asks for this — add one to the next run to measure it.</span>}
      {a.why && <span className="muted">{a.why}</span>}
      <a href="#report-win-back">Its proof is on Quick wins</a>
    </div>
  );
}

function WinBack({ run }: { run: Run }) {
  const { targets, actions } = winBackPlan(run);
  const [invs, setInvs] = useState<Investigation[]>([]);
  const [budget, setBudget] = useState<number | null>(null);
  const live = run.mode === "live_api";
  useEffect(() => {
    if (!live) return;
    getInvestigations(run.id).then(setInvs).catch(() => {});
    getHealth().then((h) => setBudget(h.why_budget_usd ?? null)).catch(() => {});
  }, [run.id, live]);
  if (!targets.length) return null;
  const onInv = (i: Investigation) => setInvs((xs) => [i, ...xs.filter((x) => x.id !== i.id)]);
  const planned = new Set(actions.map((a) => a.attribute_id));
  const unplanned = targets.filter((s) => !planned.has(s.attribute_id));
  const questions = new Set(actions.flatMap((a) => a.question_ids)).size;
  const verdicts = new Map(actions.map((a) => [a.attribute_id, matchVerdict(matchRows(a, run.retrieval?.rows ?? [])).verdict]));
  const stand = actions.filter((a) => verdicts.get(a.attribute_id) !== "worse");
  const fall = actions.filter((a) => verdicts.get(a.attribute_id) === "worse");
  const proven = actions.filter((a) => invs.some((i) => i.kind === "buyer" && i.attribute_id === a.attribute_id
    && i.verdicts.some((v) => v.fix === "copy" || v.fix === "authority"))).length;
  return (
    <Section title={<Term k="quick_wins">Quick wins</Term>}
           found={`${plural(targets.length, "claim")} with room to grow · `
             + (actions.length ? `${proven} of ${plural(actions.length, "rewrite")} proven`
                 + (questions ? ` · ${plural(questions, "unbranded question")} to win` : "")
               : "no suggested fix passed our checks yet")}>
      <p style={{ margin: 0 }}>
        For each claim with room to grow: a new passage for one of your pages, headed by a buyer's own question,
        why it should make AI name {run.profile.name}, and its proof. A draft — check every statement against the
        product before publishing. It changes no number in this report.
      </p>
      {actions.length > 0 && (
        <>
          <p className="ladder-legend muted">
            <span>① <Term k="retrieval_score">Match check</Term>: free, already done</span>
            <span>② <Term k="replay_test">Replay test</Term>: before you publish{budget != null ? `, up to $${budget.toFixed(2)} a question` : ""}</span>
            <span>③ <Term k="fix_recheck">Live check</Term>: after you publish</span>
          </p>
          <ul className="ranked">
            {stand.map((a, i) => <RewriteRow key={a.attribute_id} a={a} rank={i + 1} run={run} invs={invs} budget={budget} onInv={onInv} />)}
            {fall.length > 0 && (
              <li className="sep">Rewrites we could not stand behind ({fall.length}): our own match check says they match the buyer questions worse than today's copy</li>
            )}
            {fall.map((a) => <RewriteRow key={a.attribute_id} a={a} rank={null} run={run} invs={invs} budget={budget} onInv={onInv} />)}
          </ul>
        </>
      )}
      {unplanned.length > 0 && (
        <p className="muted" style={{ margin: 0 }}>
          No suggested fix passed our checks yet for {unplanned.map((s) => s.label).join(", ")}
          {(run.win_back_notes ?? []).length > 0 ? ": the reasons are below, or it became a claim with room to grow when the run was re-scored." : "."}
        </p>
      )}
      {(run.win_back_notes ?? []).length > 0 && (
        <details className="block">
          <summary><span className="block-title">Suggestions we could not confirm</span>
            <span className="block-found">{plural(run.win_back_notes!.length, "reason")}</span></summary>
          <div className="block-body">
            <p className="muted" style={{ margin: 0 }}>
              A suggestion is shown only if the page it names is one we read, it is headed by a buyer's question,
              it says why it should work, it does not mostly repeat the copy it replaces, and it states facts, not marketing words.
            </p>
            <ul>{run.win_back_notes!.map((n, i) => <li key={i}>{n}</li>)}</ul>
          </div>
        </details>
      )}
    </Section>
  );
}

/** Brand questions name the company and never a claim: what does AI say it is known for? */
function BrandQuestions({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const names = probeLabels(run.probes, run.topics);
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const evals = new Map(run.evaluations.map((e) => [e.probe_id, e]));
  const excluded = (id: string) => {
    const a = answers.get(id), e = evals.get(id);
    return !a || !e || !counts(a, e);
  };
  const raised = new Map<string, AttributeScore[]>();
  for (const s of run.attribute_scores) {
    for (const id of s.probe_ids) raised.set(id, [...(raised.get(id) ?? []), s]);
  }
  const named = run.probes.filter((p) => p.kind === "named" && p.phase === "baseline");
  const withClaims = named.filter((p) => raised.get(p.id)?.some((s) => !s.discovered)).length;
  const d = run.drift;
  return (
    <Section className="qset brand" title={<Term k="brand_question">Branded questions</Term>}
           found={`${named.length} asked · your claims came up in ${withClaims}`
             + (d?.excluded_named ? ` · ${d.excluded_named} excluded` : "")}>
      <details className="qhow">
        <summary>How these were asked ⓘ</summary>
        <p className="muted" style={{ margin: 0 }}>
          Each names {run.profile.name} and never a claim, so whatever AI says it is known for, it said
          unprompted. These answers drive the headline.
        </p>
      </details>
      <div className="qlist">
        {named.map((p) => (
          <QuestionRow key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)} replay={replay}
                       verdict={excluded(p.id)
                         ? <span className="tag warn">excluded from scores</span>
                         : raised.get(p.id)?.length ? <span className="muted">{plural(raised.get(p.id)!.length, "claim")}</span>
                         : undefined}
                       sub={(raised.get(p.id) ?? []).filter((s) => !s.discovered).map((s) => s.label).join(" · ") || undefined}
                       tags={(raised.get(p.id) ?? []).map((s) => (
                         <span key={s.attribute_id} className={`pill ${s.zone}`}>{s.label}</span>
                       ))} />
        ))}
      </div>
    </Section>
  );
}

/** Things AI says the company is known for that neither the company nor its site ever supplied. */
function Discovered({ run }: { run: Run }) {
  const found = run.attribute_scores.filter((s) => s.discovered);
  const toShape = found.filter((s) => s.zone === "imposed").length;
  return (
    <Section title={<>Discovered <Term k="imposed">identities</Term></>}
           found={found.length ? `${found.length} found in the answers${toShape ? ` · ${toShape} to shape` : ""}`
             : "none found"}>
      {found.length ? (
        <>
          <p className="muted" style={{ margin: 0 }}>
            Found in the answers by the discovery pass — never supplied by you or your site. Each is
            an identity AI already gives {run.profile.name}: adopt it, or reframe it.
          </p>
          <ClaimCards scores={found} run={run} />
        </>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          The answers raised nothing about {run.profile.name} beyond the claims on the Overview.
        </p>
      )}
    </Section>
  );
}

const DROPPED = "Dropped unverifiable observation — ";
const DISCOVERY = "Discovery — ";

/** One dropped reading of an answer, as "Brand question 3 — the quote … did not match word for word". */
function DroppedLine({ text, run }: { text: string; run: Run }) {
  const m = /^(.*?): (?:Attribute (\S+): quote (not verbatim|is from a citation)|Unknown attribute id '([^']+)')/.exec(text);
  if (!m) return <Linked text={text} run={run} />;
  const label = (id: string) => run.attribute_scores.find((s) => s.attribute_id === id)?.label ?? id.replaceAll("_", " ");
  return (
    <>
      <Linked text={m[1]} run={run} /> —{" "}
      {m[3] === "not verbatim" ? <>the quote for “{label(m[2])}” did not match the answer word for word</>
        : m[3] ? <>the quote for “{label(m[2])}” came from a cited source, not the answer</>
        : <>it named “{label(m[4])}”, a trait this run was not measuring</>}
    </>
  );
}

/** One possible new trait the answers suggested, and why it was not kept. */
function DiscoveryLine({ text, run }: { text: string; run: Run }) {
  const m = /^'(.+?)': (.*)$/.exec(text);
  if (!m) return <Linked text={text} run={run} />;
  const thin = /in (\d+) eligible answer\(s\), needs (\d+)/.exec(m[2]);
  return (
    <>
      “{m[1]}” —{" "}
      {thin ? `found word for word in only ${plural(Number(thin[1]), "answer")}; it needs ${thin[2]}`
        : m[2].startsWith("same attribute") ? "the same as a trait already measured"
        : <Linked text={m[2]} run={run} />}
    </>
  );
}

/** A count with its items one small toggle away. */
function Count({ summary, items }: { summary: ReactNode; items: ReactNode[] }) {
  if (!items.length) return <li>{summary}</li>;
  return (
    <li>
      <details>
        <summary>{summary}</summary>
        <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
      </details>
    </li>
  );
}

/** The whole run as JSON, workflow log included: the page shows the checks, the file keeps every step. */
function downloadRun(run: Run) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${run.profile.name.replace(/\W+/g, "-")}-${run.id}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * "How we checked this report": the drift limitations, excluded answers, dropped observations and
 * discovery notes turned into a few counts in plain sentences, each with its items behind a toggle.
 * The raw workflow log stays out of the page and in the downloadable data.
 */
function HowWeChecked({ run }: { run: Run }) {
  const d = run.drift!;
  const lim = d.limitations;
  const dropped = lim.filter((l) => l.startsWith(DROPPED)).map((l) => l.slice(DROPPED.length));
  const notVerbatim = dropped.filter((l) => l.includes("quote not verbatim")).length;
  const cited = dropped.filter((l) => l.includes("quote is from a citation")).length;
  const unknown = dropped.filter((l) => l.includes("Unknown attribute id")).length;
  const otherDrop = dropped.length - notVerbatim - cited - unknown;
  const discovery = lim.filter((l) => l.startsWith(DISCOVERY)).map((l) => l.slice(DISCOVERY.length));
  const proposals = discovery.filter((l) => /^'.+?': /.test(l));
  const rejected = proposals.filter((l) => !l.includes(": kept on its verbatim answers"));
  const thin = rejected.filter((l) => / needs \d+/.test(l)).length;
  const repeats = rejected.filter((l) => l.includes("same attribute as one already measured")).length;
  const vague = rejected.length - thin - repeats;
  const kept = run.attribute_scores.filter((s) => s.discovered);
  const small = lim.some((l) => l.startsWith("Small sample"));
  const other = [
    ...discovery.filter((l) => !proposals.includes(l)).map((l) => l[0].toUpperCase() + l.slice(1)),
    ...lim.filter((l) => !l.startsWith(DROPPED) && !l.startsWith(DISCOVERY) && !l.startsWith("Small sample")
      && !/^\d+ of \d+ brand answers were excluded/.test(l)),
  ];
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline").length;
  const tries = d.tries ?? 1, sampled = d.repeat_sample ?? 0;
  const buyerAsks = buyer + sampled * (tries - 1);
  return (
    <section className="card checks-panel">
      <h3>How we checked this report</h3>
      <ul className="checks-list">
        <li>
          <strong>{d.n_named} of {d.named_asked}</strong> <Term k="brand_question">branded question</Term> answers
          counted{d.excluded_named > 0 && `; ${d.excluded_named} left out, explained above`}.
          {small && " That is a small sample, so treat a difference of a few points as noise."}
        </li>
        {buyer > 0 && (
          <li>
            <strong>{d.n_blind} of {buyerAsks}</strong> <Term k="buyer_question">unbranded question</Term> answers
            counted ({plural(buyer, "question")} asked once
            {sampled > 0 && `, ${sampled} of them ${tries} times over`}).
          </li>
        )}
        <Count summary={<>
          <strong>{dropped.length}</strong> {dropped.length === 1 ? "reading" : "readings"} of the AI’s answers thrown away
          {notVerbatim > 0 && <>, {notVerbatim} because the quote did not match the answer word for word</>}
          {cited > 0 && <>, {cited} because the quote came from a cited source, not the answer</>}
          {unknown > 0 && <>, {unknown} for naming a trait this run was not measuring</>}
          {otherDrop > 0 && <>, {otherDrop} for another reason</>}.
          {" "}Nothing is counted without a word-for-word quote.
        </>} items={dropped.map((l, i) => <DroppedLine key={i} text={l} run={run} />)} />
        {kept.length + rejected.length > 0 && (
          <Count summary={<>
            <strong>{kept.length + rejected.length}</strong> possible new traits suggested by reading the answers
            together; {kept.length} kept{kept.length > 0 && <> ({kept.map((s) => `“${s.label}”`).join(", ")})</>}
            {thin > 0 && <>, {thin} rejected for too little support</>}
            {repeats > 0 && <>, {repeats} rejected as repeats of a trait already measured</>}
            {vague > 0 && <>, {vague} rejected as too vague to tell apart from what is measured</>}.
          </>} items={proposals.map((l, i) => <DiscoveryLine key={i} text={l} run={run} />)} />
        )}
        {other.length > 0 && (
          <Count summary={<>{plural(other.length, "more caveat")} to keep in mind</>}
                 items={other.map((l, i) => <Linked key={i} text={l} run={run} />)} />
        )}
      </ul>
      <p className="muted" style={{ margin: 0 }}>
        Every step the workflow took is in the{" "}
        <button className="linky" onClick={() => downloadRun(run)}>full data download (JSON)</button>.
      </p>
    </section>
  );
}

export function History({ runs, onOpen }: { runs: RunSummary[]; onOpen: (id: string) => void }) {
  const names = runLabels(runs);
  if (!runs.length) return <div className="card muted">No saved runs yet. Onboard a company and measure it to create one.</div>;
  return (
    <div className="stack">
      <p className="lede" style={{ margin: ".9rem 0 0" }}>
        Each run asked AI about one company and compared its answers with what the company’s own site
        says. Open one to see the gap, and what to change.
      </p>
      <div className="card">
        <table className="runs">
          <thead>
            <tr>
              <th>Run</th><th>Company</th><th>When</th><th>Source</th>
              <th><Term k="untapped_potential">Untapped potential</Term></th><th><Term k="landed">Landed</Term></th>
              <th><Term k="lost_claim">To win back</Term></th><th><Term k="imposed">To shape</Term></th>
              <th><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="pick" onClick={() => onOpen(r.id)}>
                <td data-label="Run" title={r.id}>{names[r.id]?.short ?? r.id}</td>
                <td data-label="Company"><strong>{r.company}</strong></td>
                <td data-label="When" className="muted">{r.created_at.replace("T", " ")}</td>
                <td data-label="Source">
                  {r.mode === "live_api"
                    ? <span className="pill live">{PROVENANCE_LABEL.live_api}</span>
                    : <span className="pill" title={r.scenario ? `Bundled scenario ${r.scenario}` : undefined}>Sample</span>}
                </td>
                <td>
                  <strong>{potentialText(headline(r))}</strong>
                  <div className="muted">
                    {headline(r).today ?? r.na_reasons?.headline ?? r.na_reasons?.[headline(r).field]}
                  </div>
                </td>
                <td data-label="Landed">{r.landed}</td><td data-label="To win back">{r.lost}</td>
                <td data-label="To shape">{r.imposed}</td>
                <td className="open-cell">
                  <button className="linky" onClick={(e) => { e.stopPropagation(); onOpen(r.id); }}>
                    Open report →<span className="sr-only"> for {r.company}, {names[r.id]?.short}</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
