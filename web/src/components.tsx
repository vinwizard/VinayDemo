import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { KeyboardEvent, ReactNode } from "react";
import type {
  Answer, AttributeScore, DriftReport, Probe, QueryEvaluation, RetrievalRow, Run, ScoredPassage, SearchTry,
  WinBackAction, RunSummary, VisibilitySet, Zone,
} from "./api";
import { GAP_ZONES, OWNER_TEXT, OWNER_TITLE, ZONE_ORDER, ZONES, reaskRun, rescoreRun } from "./api";
import { ADDED_MIN_WEIGHT, Slider } from "./claims";
import {
  PROVENANCE_LABEL, ZONE_LABEL, ZONE_MEANING, claimShare, headline, plain, potentialText, probeLabels,
  provenanceLabel, runLabels, when,
} from "./labels";
import { GLOSSARY } from "./glossary";
import { Popover, Term } from "./popover";

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
function Block({ title, found, children, open }: {
  title: ReactNode; found: ReactNode; children: ReactNode; open?: boolean;
}) {
  return (
    <details className="block" open={open}>
      <summary>
        <span className="block-title">{title}</span>
        <span className="block-found">{found}</span>
      </summary>
      <div className="block-body">{children}</div>
    </details>
  );
}

/** One titled part of a report tab, headed by what it found. */
function Section({ title, found, children }: { title: ReactNode; found: ReactNode; children: ReactNode }) {
  return (
    <section className="panel-sec">
      <div className="panel-sec-head">
        <h3>{title}</h3>
        <span className="block-found">{found}</span>
      </div>
      {children}
    </section>
  );
}

/** A whole run's buyer visibility or one front's: the same fields on both. */
type Vis = Pick<DriftReport, "visibility" | "tries" | "visibility_range" | "low_confidence">;

/** How often each buyer question was asked, and the spread across those tries. */
const triesText = (d: Vis) => (d.tries ?? 1) > 1 && d.visibility_range
  ? `range ${d.visibility_range[0]}–${d.visibility_range[1]} across ${d.tries} tries`
  : "1 try per question";

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

/** The gap between the two fronts in one plain sentence, or why there is only one. */
function gapSentence(d: DriftReport, brand: string): string | null {
  const fronts = frontsOf(d);
  const placed = fronts.find((v) => v.front === "placed"), aiming = fronts.find((v) => v.front === "aiming");
  const both = fronts.find((v) => v.front === "both");
  if (both) return `Where AI places ${brand} is the category its site aims for, ${both.category}, so one set of buyer questions was asked.`;
  if (placed && aiming) {
    if (d.visibility_gap == null) return null;
    const flagged = placed.low_confidence || aiming.low_confidence ? " (low confidence: see Buyer questions)" : "";
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

/** Buyer visibility, never a bare number when the control question says it is not to be trusted. */
function Visibility({ d }: { d: Vis }) {
  if (d.visibility == null) return <>n/a</>;
  return (
    <>
      {d.visibility}<small> / 100</small>
      {d.low_confidence && (
        <Term k="low_confidence" note={d.low_confidence}><span className="tag warn">low confidence</span></Term>
      )}
    </>
  );
}

/** The model that answered the questions and the separate one that judged them, as the answers record. */
const modelsOf = (run: Run) => {
  const all = [run.answers, run.repeat_answers ?? []].flat();
  const list = (xs: (string | null | undefined)[]) => [...new Set(xs.filter(Boolean))].join(", ");
  return { answered: list(all.map((a) => a.model)), judged: list(all.map((a) => a.evaluator_model)) };
};

/** The headline, buyer visibility and the claims to win back: pinned above every tab. */
function Figures({ d, brand }: { d: DriftReport; brand: string }) {
  const h = headline(d);
  const lost = d.lost_claims.length;
  const fronts = frontsOf(d);
  const gap = gapSentence(d, brand);
  return (
    <>
    <div className="figures">
      <div className="fig potential">
        <span className="fig-value">{h.potential == null ? "n/a" : `${h.potential}%`}</span>
        <span className="fig-label">
          {h.potential == null ? h.label : <Term k="untapped_potential">untapped potential</Term>}
        </span>
        <span className="fig-sub">{h.today ?? d.na_reasons?.[h.field]}</span>
      </div>
      {fronts.length ? fronts.map((v) => (
        <div className="fig" key={v.front}>
          <span className="fig-value"><Visibility d={v} /></span>
          <span className="fig-label"><FrontLabel v={v} /></span>
          <span className="fig-sub">
            {v.category} · {v.visibility == null ? "not measured" : <Term k="tries">{triesText(v)}</Term>}
          </span>
        </div>
      )) : (
        <div className="fig">
          <span className="fig-value"><Visibility d={d} /></span>
          <span className="fig-label"><Term k="buyer_visibility">buyer visibility</Term></span>
          <span className="fig-sub">{d.visibility == null ? d.na_reasons?.visibility : <Term k="tries">{triesText(d)}</Term>}</span>
        </div>
      )}
      <div className="fig">
        <span className="fig-value">{lost}</span>
        <span className="fig-label"><Term k="lost_claim">{lost === 1 ? "claim" : "claims"} to win back</Term></span>
      </div>
    </div>
    {fronts.length > 0 && gap && <p className="gap-line">{gap}</p>}
    </>
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
      {" "}Based on {d.n_named} <Term k="brand_question">brand question</Term> answers and{" "}
      {d.n_blind} <Term k="buyer_question">buyer question</Term> answers · source: {provenanceLabel(d.provenance)}
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
      ? `The comparison question: it names ${brand} beside the products AI named instead. Exploratory — never counted in the scores.`
      : `A brand question: it names ${brand} but never a claim, so whatever AI says ${brand} is known for, it said on its own.`;
  }
  if (p.phase === "control") return "The control question: can the AI name this category’s leading tools at all? Never scored.";
  if (p.phase === "followup") return `A follow-up buyer question: exploratory, never counted in the scores.`;
  return `A buyer question: it never names ${brand}, so it shows whether AI brings ${brand} up on its own.`;
}

/**
 * "Brand question 2" as something you can read in place: hover or tap shows the question, whether
 * it counted and why not, and the AI's answer — no trip to another tab.
 */
function QRef({ id, run }: { id: string; run: Run }) {
  const p = run.probes.find((x) => x.id === id);
  const name = probeLabels(run.probes, run.topics)[id] ?? id;
  if (!p) return <>{name}</>;
  const a = run.answers.find((x) => x.probe_id === id), e = run.evaluations.find((x) => x.probe_id === id);
  const why = p.phase === "baseline" ? leftOut(a, e, run.profile.name) : null;
  const tab = p.kind === "named" && p.phase !== "followup" ? "brand" : p.kind === "named" ? "sources" : "buyer";
  return (
    <Popover wide label={name} className="qref" trigger={name}>
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
      <div className="chips" role="list">
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
      the OpenAI Responses API with web search{judged && `, judged by a separate model (${judged})`}. This
      measures that API at this moment, not the ChatGPT consumer app. Answers with no search behind
      them are excluded from scores.
    </p>
  );
}

const TABS = [
  ["overview", "Overview"], ["win-back", "Win it back"], ["buyer", "Buyer questions"],
  ["why", "Why AI misses you"], ["brand", "Brand questions"], ["sources", "Sources & rivals"],
] as const;

/** A tab label's native tooltip, for the two tabs named after a term this product invented. */
const TAB_HINT: Partial<Record<ReportTab, string>> = {
  buyer: GLOSSARY.buyer_question.def, brand: GLOSSARY.brand_question.def,
};
type ReportTab = (typeof TABS)[number][0];

/** "#report-buyer" opens the Buyer questions tab, so a link can land on one. */
const tabFromHash = (): ReportTab =>
  TABS.find(([t]) => window.location.hash === `#report-${t}`)?.[0] ?? "overview";

const sortClaims = (scores: AttributeScore[]) => [...scores].sort(
  (a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.mention_rate ?? b.echo_rate ?? 0) - (a.mention_rate ?? a.echo_rate ?? 0),
);

/**
 * One run as a product: a summary pinned at the top, then one tab per question a reader asks —
 * each fitting about one screen — with every claim and question readable in place. Same numbers
 * and data as ever; only the layout. `onRescored` enables the optional weights step; without it the
 * report is read-only. `weightNote` replaces the weights step with one plain line.
 */
export function Report({ run, onRescored, weightNote }: {
  run: Run;
  onRescored?: (r: Run) => void;
  weightNote?: string;
}) {
  const d = run.drift;
  const uid = useId();
  const top = useRef<HTMLDivElement>(null);
  const [tab, setTabState] = useState<ReportTab>(tabFromHash);
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
  const setTab = (t: ReportTab, focus = false) => {
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
  const count: Record<ReportTab, number | undefined> = {
    overview: claims.length,
    "win-back": winBackPlan(run).actions.length,
    buyer: run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline").length,
    brand: run.probes.filter((p) => p.kind === "named" && p.phase === "baseline").length,
    why: undefined,
    sources: run.insights?.sources.sources.length,
  };

  return (
    <article className="report">
      <div className="report-top" ref={top}>
        <div className="report-head">
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
          {d && <Figures d={d} brand={run.profile.name} />}
          {d && <PrintSummary run={run} />}
        </div>
        {d && (
          <div className="report-tabs" role="tablist" aria-label="Report sections" onKeyDown={onKey}>
            {TABS.map(([t, label]) => (
              <button key={t} id={`${uid}-tab-${t}`} role="tab" className="rtab" aria-selected={tab === t}
                      aria-controls={`${uid}-panel-${t}`} tabIndex={tab === t ? 0 : -1} onClick={() => setTab(t)}
                      title={TAB_HINT[t]}>
                {label}
                {count[t] != null && <span className="rtab-count">{count[t]}</span>}
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
              {weightNote ? <p className="muted">{weightNote}</p>
                : onRescored && <Weights key={run.id} run={run} onRescored={onRescored} />}
              <HowWeChecked run={run} />
            </>
          )}
          {tab === "win-back" && (
            <>
              <WinBack run={run} />
              <Section title="Where the upside is" found="the biggest open claims first">
                <GapCards run={run} />
              </Section>
            </>
          )}
          {tab === "buyer" && <BuyerQuestions run={run} />}
          {tab === "why" && <><WhatItSearched run={run} /><TestAFix run={run} /></>}
          {tab === "brand" && <BrandQuestions run={run} />}
          {tab === "sources" && (
            <>
              <CitedSources run={run} />
              <ShareOfVoice run={run} />
              <Competitors run={run} />
              <Discovered run={run} />
            </>
          )}
        </div>
      ) : (
        <>
          <RunSource run={run} />
          <div className="callout">This run finished without a drift report.</div>
        </>
      )}
    </article>
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
              <Visibility d={v} />{v.visibility != null && ` — ${triesText(v)}`}
              {v.low_confidence && <><br /><span className="muted">{v.low_confidence}</span></>}
              <br />
            </span>
          ))}
          {gapSentence(d, run.profile.name)}
        </p>
      ) : (
        <p className="exec-vis">
          <strong>Buyer visibility:</strong> <Visibility d={d} />
          {d.visibility == null ? ` — ${d.na_reasons?.visibility ?? "not measured"}` : ` — ${triesText(d)}`}
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
        <br />Independent portfolio demo — not a Profound product or integration.
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
          <h4>How to win it back</h4>
          <FixCard a={fix} run={run} />
        </>
      )}
      {s.owner === "authority_gap" && (
        <p className="muted">
          Relevant capability:{" "}
          <a href="https://www.tryprofound.com/features/answer-engine-insights" target="_blank" rel="noreferrer">
            Answer Engine Insights / citation analysis
          </a>
        </p>
      )}
    </div>
  );
}

function GapCard({ s, run }: { s: AttributeScore; run: Run }) {
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>{s.label}</h3>
        <Term k={s.zone}><span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span></Term>
      </div>
      <p style={{ margin: ".4rem 0 0" }}><strong>{OWNER_TITLE[s.owner]}.</strong> {OWNER_TEXT[s.owner]}</p>
      {s.limitations.filter((l) => l.includes("does not endorse it")).map((l, i) => (
        <p className="warn" key={i} style={{ margin: ".3rem 0 0" }}>{l}</p>
      ))}
      {s.discovered && <p className="muted" style={{ margin: ".3rem 0 0" }}>Discovered from the answers.</p>}
      <p className="muted" style={{ margin: ".3rem 0 0" }}>
        Your site: {siteShare(s)} · AI: {aiShare(s)}
      </p>
      {s.quotes[0] && <p className="quote">{plain(s.quotes[0])}</p>}
      {s.owner === "authority_gap" && (
        <p className="muted" style={{ marginBottom: 0 }}>
          Relevant capability:{" "}
          <a href="https://www.tryprofound.com/features/answer-engine-insights" target="_blank" rel="noreferrer">
            Answer Engine Insights / citation analysis
          </a>
        </p>
      )}
      {s.owner === "messaging_gap" && (
        <p className="muted" style={{ marginBottom: 0 }}>
          Not an AI problem: your own copy does not state this clearly enough to be repeated.
        </p>
      )}
      <div style={{ marginTop: ".4rem" }}>
        <Popover wide label={s.label} className="linky" trigger="All evidence"><ClaimDetail s={s} run={run} /></Popover>
      </div>
    </div>
  );
}

function GapCards({ run }: { run: Run }) {
  const gaps = run.attribute_scores
    .filter((s) => GAP_ZONES.includes(s.zone))
    .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
    .slice(0, 4);
  if (!gaps.length) {
    return <div className="card muted">No open opportunity: every claim has landed or is unweighted.</div>;
  }
  return (
    <div className="gaps">
      {gaps.map((s) => <GapCard key={s.attribute_id} s={s} run={run} />)}
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
 * Every product named in a buyer answer, beside the line that names it, and what AI said when asked
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
          ? "No buyer question was asked — nothing is weighted as intended — so the buyer axis was not measured and no other product could be named."
          : replay
            ? "This sample scenario names no competitor in its authored buyer answers. Replay never asks the comparison question either: that round exists only in a live run."
            : "No other product was named in any buyer answer that counts toward the scores, so there was nothing to compare against and no comparison question was asked."}
        </p>
      </Section>
    );
  }
  const top = rows[0];
  const namedTable = (shown: typeof rows) => (
    <table className="named">
      <thead>
        <tr><th>Product</th>{repeats && <th>Answers</th>}<th>Buyer topic</th><th>Where the answer names it</th></tr>
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
           found={`${plural(rows.length, "product")} named${repeats ? ` · most often ${top.name} (${top.count})` : ""}`}>
      <p className="muted" style={{ margin: "0 0 .6rem" }}>
        {replay
          ? "Authored sample data, not a measurement: no model volunteered these names. A live run"
            + " puts here the brands the model itself offered when a buyer described what you do"
            + " without naming you, and only a live run asks the comparison question below."
          : `Every product the model named when a buyer asked about what ${run.profile.name} does`
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
          <summary className="muted">Show the other {plural(rows.length - SHOWN_NAMED, "product")}</summary>
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
  const title = <><Term k="share_of_voice">Share of voice</Term> on buyer questions</>;
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
           found={`On ${v.questions} buyer questions, AI recommended ${v.brand} ${plural(v.brand_recommended, "time")} and ${rivalText}`}>
      <p className="muted" style={{ margin: 0 }}>
        {run.mode !== "live_api" && <>{SAMPLE_NOTE} </>}
        How many of the {v.questions} buyer questions that count got an answer recommending each product. None
        of those questions named {v.brand}; a mention without a recommendation does not count, and a product
        counts once per answer, however often it repeats.
      </p>
      <div className="sov" role="list" aria-label={`Answers recommending each product, out of ${v.questions}`}>
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

const SHOWN_SOURCES = 8;
const SHOWN_NAMED = 3;

/**
 * The sites AI cited in the answers that count, ranked by how many answers cite each. A third-party
 * site cited more than once is flagged as a target: being on the pages AI reads is the lever.
 */
function CitedSources({ run }: { run: Run }) {
  const s = run.insights?.sources;
  const title = "Where AI gets its opinion";
  if (!s) return null;
  if (s.reason) {
    return (
      <Section title={title} found="no citations">
        <p className="muted" style={{ margin: 0 }}>{s.reason}</p>
      </Section>
    );
  }
  const targets = s.sources.filter((r) => r.target);
  const rows = s.sources.slice(0, SHOWN_SOURCES);
  const rest = s.sources.length - rows.length;
  return (
    <Section title={title}
           found={`${plural(s.sources.length, "site")} cited · most often ${s.sources[0].domain} (${plural(s.sources[0].answers, "answer")})`
             + ` · ${targets.length ? `${targets.length} to target` : "none to target yet"}`}>
      <p className="muted" style={{ margin: 0 }}>
        {run.mode !== "live_api" && <>{SAMPLE_NOTE} Every example.com address is a fictional placeholder. </>}
        {s.cited_answers} of the {s.answers} buyer and brand answers that count cite at least one source.
        A third-party site cited in more than one answer is worth a presence: it is where AI reads about
        this market. A citation shows what the model read, not why it answered as it did.
      </p>
      <table className="named">
        <thead>
          <tr><th>Site</th><th>Answers citing it</th><th>In buyer · brand answers</th><th>Whose</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.domain}>
              <td><strong>{r.domain}</strong></td>
              <td>{r.answers}</td>
              <td className="muted">{r.buyer} · {r.brand}</td>
              <td>
                {r.owned ? <span className="pill landed">your site</span>
                  : r.target ? <span className="pill lost_claim">third party · target</span>
                  : <span className="muted">third party</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rest > 0 && <p className="muted" style={{ margin: 0 }}>+ {plural(rest, "more site")}, none cited more often than those above.</p>}
    </Section>
  );
}

const PHONE = "(max-width: 600px)";

/** A cited page without its scheme, "www." or trailing slash. */
const page = (u: string) => u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");

/** Searches as “a”, “b” and “c”. */
const quoted = (qs: string[]) => qs.map((q, i) => (
  <span key={i}>{i ? (i === qs.length - 1 ? " and " : ", ") : ""}“{q}”</span>
));

/** One try in one sentence: what the model searched, how many pages it cited, and whether any was yours. */
function tryStory(t: SearchTry) {
  const own = t.owned_pages.length;
  return (
    <>
      {t.searches.length ? <>ChatGPT searched {quoted(t.searches)}</> : "ChatGPT answered without searching"}
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
      <h4>What ChatGPT searched <Term k="fan_out" icon /></h4>
      {tries ? tries.map((t) => (
        <p key={t.try_no}>
          {run.mode !== "live_api" && <span className="tag sample">sample</span>}
          {tries.length > 1 && <strong>Try {t.try_no}: </strong>}{tryStory(t)}
        </p>
      )) : <p className="muted">Not recorded for this run.</p>}
    </div>
  );
}

/**
 * The model's own web searches for the buyer questions, near-duplicates grouped: a story from one
 * question, then every search with the questions it came from and the pages cited after it.
 */
function WhatItSearched({ run }: { run: Run }) {
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
  const found = s.reason ? (s.answers ? "no web searches" : buyer.some((p) => answeredOk(run, p)) ? "not recorded" : "no buyer answers") : `ChatGPT ran ${plural(s.searches.length, "different search", "different searches")};`
    + ` your site was cited after ${s.owned ? s.owned : "none"} of them`;
  return (
    <Block open={!window.matchMedia(PHONE).matches} title="What ChatGPT searched" found={found}>
      {s.reason ? <p className="muted" style={{ margin: 0 }}>{s.reason}</p> : (
        <>
          <p className="muted" style={{ margin: 0 }}>
            {replay && <>{SAMPLE_NOTE} The searches were written by hand too. </>}
            To answer a buyer, the AI first runs a few <Term k="fan_out">web searches</Term> of its own.
            A search that never leads to your site is where you go missing. Tap one for details.
          </p>
          {story && (
            <p className="callout story">
              {replay && <span className="tag sample">sample</span>}
              When a buyer asked “{story.text}”, {tryStory(first(story)!)}
            </p>
          )}
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
        </>
      )}
    </Block>
  );
}

const score = (x: number) => x.toFixed(2);
const behind = (r: RetrievalRow) => !!(r.yours && r.rival && r.rival.score > r.yours.score);

/** The one gap a fix does the most for: the question where the rewrite lifts your score the most. */
function biggestFix(run: Run): RetrievalRow | undefined {
  const lift = (r: RetrievalRow) => (r.fixed && r.yours ? r.fixed.score - r.yours.score : -1);
  return (run.retrieval?.rows ?? []).filter((r) => behind(r) && lift(r) > 0).sort((a, b) => lift(b) - lift(a))[0];
}

/** Your passage, the cited page's and yours with the fix, as three bars on one scale (0 to 1). */
function ScoreBars({ r }: { r: RetrievalRow }) {
  const bars = [
    ["You", r.yours, "var(--muted)"], ["Page AI cited", r.rival, "var(--contested)"],
    ["With the fix", r.fixed, "var(--landed)"],
  ] as const;
  return (
    <span className="score-bars">
      {bars.filter(([, p]) => p).map(([label, p, fill]) => (
        <span key={label} className="score-bar">
          <span className="score-label">{label}</span>
          <span className="bar-track thin"><span className="bar" style={{ width: `${Math.max(2, p!.score * 100)}%`, background: fill }} /></span>
          <span className="score-num">{score(p!.score)}</span>
        </span>
      ))}
    </span>
  );
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
function Reask({ run, r, got, setGot }: {
  run: Run; r: RetrievalRow; got: RetrievalRow["reask"]; setGot: (got: RetrievalRow["reask"]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (run.mode !== "live_api" || !r.fixed) return null;
  const ask = () => {
    setBusy(true); setError(null);
    reaskRun(run.id, r.probe_id)
      .then((next) => setGot(next.retrieval?.rows.find((x) => x.probe_id === r.probe_id)?.reask ?? null))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <div className="reask">
      {got ? (
        <p style={{ margin: 0 }}>
          <span className="tag sample">simulation</span>{" "}
          Handed the rewritten passage and the cited page as its only sources, {got.model}{" "}
          {got.named ? <strong className="own">named {run.profile.name}.</strong> : <strong>still did not name {run.profile.name}.</strong>}
        </p>
      ) : (
        <button type="button" className="primary" disabled={busy} onClick={ask}>
          {busy ? "Asking…" : "Ask the AI again with the fix"}
        </button>
      )}
      <p className="muted" style={{ margin: 0 }}>
        {got ? "One ask, not a measurement: it changes no number." : "One model call on your pass. A simulation: the AI is handed both passages as its only sources, so it shows whether the rewrite would be used, not whether a real search finds it."}
      </p>
      {error && <div className="callout error">{error}</div>}
    </div>
  );
}

/**
 * Test a fix: per buyer question, your best passage against the best passage of a page AI cited,
 * and yours again with the win-back rewrite in the page. Similarity only, labelled as a simulation.
 */
function TestAFix({ run }: { run: Run }) {
  const [reasks, setReasks] = useState<Record<string, RetrievalRow["reask"]>>({});
  const sim = run.retrieval;
  if (!sim) return null;
  const replay = sim.provenance !== "live_api";
  const probes = new Map(run.probes.map((p) => [p.id, p]));
  const fixes = new Map((run.win_back ?? []).map((a) => [a.attribute_id, a]));
  const compared = sim.rows.filter((r) => r.yours && r.rival);
  const weaker = compared.filter(behind).length;
  const found = compared.length
    ? `Your best page is weaker than the page AI cited for ${weaker} of ${plural(compared.length, "buyer question")}`
    : "no page AI cited could be compared";
  const rows = [...sim.rows].sort((a, b) => Number(!!b.fixed) - Number(!!a.fixed) || Number(behind(b)) - Number(behind(a)));
  return (
    <Block open={!window.matchMedia(PHONE).matches} title="Test a fix" found={found}>
      <p className="muted" style={{ margin: 0 }}>
        {replay && <>Authored sample, not computed: the passages and scores were written by hand to show this panel. </>}
        We split your pages and the pages AI cited into short passages and scored how closely each
        matches the question and ChatGPT's searches for it: a <Term k="retrieval_score">retrieval score</Term> from
        0 to 1. Then we put the suggested rewrite from “Win it back” into your page and scored it again.
        A simulation of what the AI reads first, not a promise of a citation. Tap a question for the passages.
      </p>
      <ul className="search-list">
        {rows.map((r) => {
          const p = probes.get(r.probe_id);
          const fix = r.fix_attribute_id ? fixes.get(r.fix_attribute_id) : undefined;
          return (
            <li key={r.probe_id}>
              <Popover wide label={`Passages for: ${p?.text ?? r.probe_id}`} className="search-row fix-row"
                       trigger={<>
                         <span className="search-q">{p?.text ?? r.probe_id}</span>
                         <ScoreBars r={r} />
                       </>}>
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
                    <Reask run={run} r={r} got={reasks[r.probe_id] ?? r.reask}
                           setGot={(got) => setReasks((m) => ({ ...m, [r.probe_id]: got }))} />
                  </>
                ) : <p className="muted">No suggested fix targets this question.</p>}
                <p className="muted">Scored against {plural(r.queries, "search", "searches")}: the question and ChatGPT's own searches for it; the best match counts.</p>
              </Popover>
            </li>
          );
        })}
      </ul>
      {sim.skipped.length > 0 && (
        <details className="skipped">
          <summary className="muted">What we could not read ({sim.skipped.length})</summary>
          <ul>{sim.skipped.map((x, i) => <li key={i} className="muted">{x}</li>)}</ul>
        </details>
      )}
      {!replay && <p className="muted" style={{ margin: 0 }}>{plural(sim.passages, "passage")} from {plural(sim.pages, "page")}, scored with {sim.model}.</p>}
    </Block>
  );
}

/** Overview's one line on the gap a suggested fix does the most for. */
function FixLine({ run, onOpen }: { run: Run; onOpen: () => void }) {
  const r = biggestFix(run);
  if (!r?.yours || !r.rival || !r.fixed) return null;
  const q = run.probes.find((p) => p.id === r.probe_id);
  return (
    <p className="callout story">
      {run.retrieval?.provenance !== "live_api" && <span className="tag sample">sample</span>}{" "}
      <strong>Biggest fixable gap:</strong> for “{q?.text}”, your best page scores {score(r.yours.score)} and
      the page AI cited {score(r.rival.score)}. With the suggested rewrite yours scores {score(r.fixed.score)}{" "}
      (<Term k="retrieval_score">simulated</Term>).{" "}
      <button type="button" className="pop-trigger linky" onClick={onOpen}>Test a fix</button>
    </p>
  );
}

/** One question as a compact row; opening it shows the full answer and what the scorer made of it. */
function QuestionRow({ p, name, answer, verdict, tags, note, replay, after }: {
  p: Probe; name: string; answer?: Answer; verdict?: ReactNode; tags?: ReactNode; note?: ReactNode;
  replay: boolean; after?: ReactNode;
}) {
  return (
    <details className="qrow">
      <summary>
        <span className="muted" title={p.id}>{name}</span>
        <span className="qrow-text">{p.text}</span>
        {verdict}
      </summary>
      <div className="qrow-body">
        {tags && <div className="row" style={{ flexWrap: "wrap", gap: ".3rem" }}>{tags}</div>}
        {note}
        <p className="muted long-answer">
          {answer && replay && <span className="tag sample">sample</span>}
          {answer ? plain(answer.text) : "no answer"}
        </p>
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
  const excluded = base.length * tries - all.length;
  const verdict = (p: Probe) => {
    if (tries > 1) {
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
  const card = (p: Probe) => {
    const shown = triesOf(p);
    return (
      <QuestionRow key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)}
                   verdict={verdict(p)} replay={replay}
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
    <>
      <Section title={<Term k="buyer_question">Buyer questions</Term>}
               found={!base.length ? na(d?.na_reasons, "visibility")
                 : `${base.length} asked${tries > 1 ? ` × ${tries} tries` : " · 1 try each"}`
                   + ` · named you in ${namedIn} of ${all.length} answers${recIn ? ` · recommended you in ${recIn}` : ""}`
                   + (excluded ? ` · ${excluded} excluded` : "")}>
        <p className="muted" style={{ margin: 0 }}>
          What a buyer would ask without naming {brand}. Each one AI answered without
          bringing {brand} up is room to be found.
          {fronts.length > 1 && ` They are asked on two fronts, half each: the category AI’s brand answers`
            + ` already place ${brand} in, and the category its own site aims for.`}
          {tries > 1
            ? ` The model answers the same question differently each time, so each was asked ${tries} times in a fresh`
              + ` context: buyer visibility is the average of the ${tries} tries, shown with its range.`
            : replay ? " A sample run replays one authored answer per question: 1 try." : " Each was asked once."}
        </p>
        {fronts.length > 0 && d && gapSentence(d, brand) && <p style={{ margin: 0 }}>{gapSentence(d, brand)}</p>}
        {!fronts.length && vis != null && (
          <p style={{ margin: 0 }}>
            <strong>Buyer visibility <Visibility d={d!} /></strong> <span className="muted">— {triesText(d!)}</span>
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
                <FrontLabel v={v} /> · {v.category} — <Visibility d={v} />{" "}
                <span className="muted">{v.visibility == null ? "not measured" : triesText(v)}</span>
              </h4>
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
      </Section>
      {!fronts.length && control && d && <Control run={run} p={control} v={d} />}
    </>
  );
}

/**
 * The control question of one set: can the answering model name this category's leading tools, and
 * does it count the brand among them? It is not a buyer question and never moves visibility; it only
 * says whether that set's number can be trusted.
 */
function Control({ run, p, v }: { run: Run; p: Probe; v: Vis }) {
  const a = run.answers.find((x) => x.probe_id === p.id);
  const e = run.evaluations.find((x) => x.probe_id === p.id);
  const flag = v.low_confidence;
  const ok = a && e && counts(a, e);
  const found = !ok ? "could not be scored"
    : `named ${plural(e.competitor_recommendations.length + (e.mentioned ? 1 : 0), "tool")}`
      + ` · ${e.mentioned ? `including ${run.profile.name}` : `not ${run.profile.name}`}`;
  return (
    <Section title="Control question"
             found={flag ? <><Term k="low_confidence"><span className="tag warn">low confidence</span></Term> {found}</> : found}>
      <p className="muted" style={{ margin: 0 }}>
        One question asked beside the buyer questions and never scored: does the answering model know
        who leads this category, and is {run.profile.name} among them? If not, this set’s buyer
        visibility is flagged low confidence.
      </p>
      {flag && <div className="callout warn-box" style={{ margin: 0 }}><strong>Low confidence.</strong> {flag}</div>}
      {!flag && ok && v.visibility === 0 && (
        <p style={{ margin: 0 }}>
          The model names {run.profile.name} among this category’s leading tools, yet never brought it
          up for a buyer: the 0 is a finding, not a gap in what the model knows.
        </p>
      )}
      <div className="qlist">
        <QuestionRow p={p} name="Control question" answer={a} replay={run.mode !== "live_api"}
                     note={ok && e.competitor_recommendations.length > 0 && (
                       <span className="muted">Tools it named: {e.competitor_recommendations.join(", ")}</span>
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

/** One verified fix: the page to change, the suggested rewrite and the buyer questions it serves. */
function FixCard({ a, run }: { a: WinBackAction; run: Run }) {
  const zone = run.attribute_scores.find((s) => s.attribute_id === a.attribute_id)?.zone ?? a.zone;
  const probes = new Map(run.probes.map((p) => [p.id, p]));
  return (
    <div className="question">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <strong>{a.label}</strong>
        <span className={`pill ${zone}`}>{ZONE_LABEL[zone]}</span>
      </div>
      <span className="muted">
        Page to change: <a href={a.page_url} target="_blank" rel="noreferrer">{a.page_url}</a>
        {a.current_copy ? " · replace:" : " · add new copy"}
      </span>
      {a.current_copy && <p className="quote">{a.current_copy}</p>}
      <p style={{ margin: 0 }}>
        {run.mode !== "live_api" && <span className="tag sample">sample</span>}{" "}
        <strong>Suggested rewrite:</strong> {a.rewrite}
      </p>
      {a.question_ids.length ? (
        <ul style={{ margin: 0 }}>
          {a.question_ids.map((q) => (
            <li key={q}><QRef id={q} run={run} />: {probes.get(q)?.text}</li>
          ))}
        </ul>
      ) : (
        <span className="muted">No buyer question in this run asks for this — add one to the next run to measure it.</span>
      )}
      {a.why && <span className="muted">{a.why}</span>}
    </div>
  );
}

function WinBack({ run }: { run: Run }) {
  const { targets, actions } = winBackPlan(run);
  if (!targets.length) return null;
  const planned = new Set(actions.map((a) => a.attribute_id));
  const unplanned = targets.filter((s) => !planned.has(s.attribute_id));
  const questions = new Set(actions.flatMap((a) => a.question_ids)).size;
  return (
    <Section title="How to win it back"
           found={actions.length ? `${plural(actions.length, "fix", "fixes")} · ${plural(questions, "buyer question")} to win`
             : "no verified fix"}>
      <p className="muted" style={{ margin: 0 }}>
        For each claim to win back or amplify: the page of yours to change, a suggested rewrite, and
        the buyer questions that did not recommend {run.profile.name} which it should help with. A
        draft — check every statement against the product before publishing, then measure again.
        It changes no number in this report.
      </p>
      {actions.length > 0 && (
        <div className="questions">
          {actions.map((a) => <FixCard key={a.attribute_id} a={a} run={run} />)}
        </div>
      )}
      {unplanned.length > 0 && (
        <p className="muted" style={{ margin: 0 }}>
          No fix yet for {unplanned.map((s) => s.label).join(", ")}
          {(run.win_back_notes ?? []).length > 0 ? " — it has no verified action (see below), or became a target when the run was re-scored." : " — no verified action was proposed for it."}
        </p>
      )}
      {(run.win_back_notes ?? []).length > 0 && (
        <>
          <h4>Dropped as unverifiable</h4>
          <ul>{run.win_back_notes!.map((n, i) => <li key={i} className="log">{n}</li>)}</ul>
        </>
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
    <Section title={<Term k="brand_question">Brand questions</Term>}
           found={`${named.length} asked · your claims came up in ${withClaims}`
             + (d?.excluded_named ? ` · ${d.excluded_named} excluded` : "")}>
      <p className="muted" style={{ margin: 0 }}>
        Each names {run.profile.name} and never a claim, so whatever AI says it is known for, it said
        unprompted. These answers drive the headline.
      </p>
      <div className="qlist">
        {named.map((p) => (
          <QuestionRow key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)} replay={replay}
                       verdict={excluded(p.id)
                         ? <span className="tag warn">excluded from scores</span>
                         : raised.get(p.id)?.length ? <span className="muted">{plural(raised.get(p.id)!.length, "claim")}</span>
                         : undefined}
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
  const tries = d.tries ?? 1;
  return (
    <section className="card checks-panel">
      <h3>How we checked this report</h3>
      <ul className="checks-list">
        <li>
          <strong>{d.n_named} of {d.named_asked}</strong> <Term k="brand_question">brand question</Term> answers
          counted{d.excluded_named > 0 && `; ${d.excluded_named} left out, explained above`}.
          {small && " That is a small sample, so treat a difference of a few points as noise."}
        </li>
        {buyer > 0 && (
          <li>
            <strong>{d.n_blind} of {buyer * tries}</strong> <Term k="buyer_question">buyer question</Term> answers
            counted ({plural(buyer, "question")}{tries > 1 ? ` × ${tries} tries each` : ", asked once each"}).
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

export function Compare({ a, b, runs = [] }: { a: Run; b: Run; runs?: RunSummary[] }) {
  const names = runLabels(runs);
  const name = (r: Run) => names[r.id]?.full ?? r.id;
  const labels = [...new Set([...a.attribute_scores, ...b.attribute_scores].map((s) => s.label))];
  const find = (r: Run, label: string) => r.attribute_scores.find((s) => s.label === label);
  // Intended rows compare the endorsement rate that drives alignment; an imposed row has no
  // positioning to land, so it compares how often AI raises it at all.
  const rate = (s: AttributeScore) => (s.intended_weight ? s.echo_rate : s.mention_rate);
  const shown = (s: AttributeScore) =>
    rate(s) == null ? "n/a" : `${pct(rate(s))}% ${s.intended_weight ? "endorsed" : "mentioned"}`;
  const cell = (s?: AttributeScore) => !s ? <span className="muted">—</span> : (
    <>
      <span className={`pill ${s.zone}`}>{shown(s)}</span>
      {rate(s) == null && <div className="muted">{na(s.na_reasons, "echo_rate")}</div>}
    </>
  );
  const ha = a.drift ? headline(a.drift) : null, hb = b.drift ? headline(b.drift) : null;
  // Change in untapped potential: going down is the good direction.
  const change = ha && hb && ha.label === hb.label && ha.potential != null && hb.potential != null
    ? Math.round((hb.potential - ha.potential) * 10) / 10 : null;
  const side = (r: Run, h: typeof ha, align: "left" | "right") => (
    <div style={{ textAlign: align }}>
      <div className="muted" title={r.id}>{name(r)}</div>
      <div className="value" style={{ fontSize: "1.6rem", fontWeight: 600 }}>
        {h?.potential == null ? "n/a" : `${h.potential}%`} <small className="muted">untapped potential</small>
      </div>
      <div className="muted">{h ? h.today ?? r.drift?.na_reasons?.[h.field] : "This run finished without a drift report."}</div>
    </div>
  );
  return (
    <div className="stack">
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          {side(a, ha, "left")}
          <div style={{ textAlign: "center" }}>
            <div className="muted">change in untapped potential</div>
            <div className={`value ${change == null ? "" : change <= 0 ? "delta up" : "delta down"}`}
                 style={{ fontSize: "1.6rem", fontWeight: 600 }}>
              {change == null ? "—" : `${change > 0 ? "+" : ""}${change} pts`}
            </div>
            {ha && hb && ha.label !== hb.label && (
              <div className="muted">{ha.label} vs {hb.label}: different headlines, not comparable</div>
            )}
          </div>
          {side(b, hb, "right")}
        </div>
      </div>
      <div className="card">
        <div className="cmp muted" style={{ borderTop: "none" }}>
          <div>Attribute</div><div>{names[a.id]?.short ?? "A"}</div>
          <div>{names[b.id]?.short ?? "B"}</div><div>Zone change</div>
        </div>
        {labels.map((label) => {
          const sa = find(a, label), sb = find(b, label);
          const moved = sa && sb && sa.zone !== sb.zone;
          return (
            <div className="cmp" key={label}>
              <div>{label}</div>
              <div>{cell(sa)}</div>
              <div>{cell(sb)}</div>
              <div className="muted">
                {!sa || !sb ? "only in one run" : moved ? `${ZONE_LABEL[sa.zone]} → ${ZONE_LABEL[sb.zone]}` : "unchanged"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function History({ runs, onOpen }: { runs: RunSummary[]; onOpen: (id: string) => void }) {
  const names = runLabels(runs);
  if (!runs.length) return <div className="card muted">No saved runs yet. Measure drift to create one.</div>;
  return (
    <div className="card">
      <table>
        <thead>
          <tr><th>Run</th><th>When</th><th>Scenario</th><th>Untapped potential</th><th>Landed</th><th>To win back</th><th>To shape</th></tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="pick" onClick={() => onOpen(r.id)}>
              <td title={r.id}>{names[r.id]?.short ?? r.id}</td>
              <td className="muted">{r.created_at.replace("T", " ")}</td>
              <td>{r.scenario ?? "—"}</td>
              <td>
                <strong>{potentialText(headline(r))}</strong>
                <div className="muted">
                  {headline(r).today ?? r.na_reasons?.headline ?? r.na_reasons?.[headline(r).field]}
                </div>
              </td>
              <td>{r.landed}</td><td>{r.lost}</td><td>{r.imposed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
