import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { KeyboardEvent, ReactNode } from "react";
import type { Answer, AttributeScore, DriftReport, Probe, QueryEvaluation, Run, WinBackAction, RunSummary, Zone } from "./api";
import { GAP_ZONES, OWNER_TEXT, OWNER_TITLE, ZONE_ORDER, ZONES, rescoreRun } from "./api";
import { ADDED_MIN_WEIGHT, Slider } from "./claims";
import {
  PROVENANCE_LABEL, ZONE_LABEL, ZONE_MEANING, claimShare, headline, plain, potentialText, probeLabels,
  provenanceLabel, runLabels, when,
} from "./labels";

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
  title: string; found: ReactNode; children: ReactNode; open?: boolean;
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
function Section({ title, found, children }: { title: string; found: ReactNode; children: ReactNode }) {
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

const ZONE_COUNT: Record<Zone, (d: DriftReport) => number> = {
  landed: (d) => d.landed.length,
  lost_claim: (d) => d.lost_claims.length,
  contested: (d) => d.contested?.length ?? 0,
  unstated_intent: (d) => d.unstated_intent.length,
  imposed: (d) => d.imposed.length,
  unprioritised: (d) => d.unprioritised?.length ?? 0,
};

/** The headline, buyer visibility and the claims to win back: pinned above every tab. */
function Figures({ d }: { d: DriftReport }) {
  const h = headline(d);
  const lost = d.lost_claims.length;
  return (
    <div className="figures">
      <div className="fig potential">
        <span className="fig-value">{h.potential == null ? "n/a" : `${h.potential}%`}</span>
        <span className="fig-label">{h.potential == null ? h.label : "untapped potential"}</span>
        <span className="fig-sub">{h.today ?? d.na_reasons?.[h.field]}</span>
      </div>
      <div className="fig">
        <span className="fig-value">{d.visibility == null ? "n/a" : d.visibility}{d.visibility != null && <small> / 100</small>}</span>
        <span className="fig-label">buyer visibility</span>
        {d.visibility == null && <span className="fig-sub">{d.na_reasons?.visibility}</span>}
      </div>
      <div className="fig">
        <span className="fig-value">{lost}</span>
        <span className="fig-label">{lost === 1 ? "claim" : "claims"} to win back</span>
      </div>
    </div>
  );
}

/** What the pinned figures mean, the zone legend and any excluded answers: the top of the Overview. */
function Explain({ d, brand }: { d: DriftReport; brand: string }) {
  return (
    <>
      <p className="muted" style={{ margin: 0 }}>
        {d.lens === "claim"
          ? `Untapped potential is weighted by how often your site states each claim: the share of what the site says that AI’s answers about ${brand} do not yet repeat supportively.`
          : `Untapped potential is weighted by how much each claim matters to you: the share of what you want to be known for that AI’s answers about ${brand} do not yet say.`}
        {" "}Buyer visibility is how often {brand} came up when a buyer asked without naming it — a
        mention scores half, a recommendation full; a separate measure that does not move the headline.
        {" "}{d.n_named} brand questions answered drive the headline · {d.n_blind} buyer questions answered
        drive buyer visibility · source: {provenanceLabel(d.provenance)}
      </p>
      <div className="zones" role="list" aria-label="Claims by zone">
        {ZONES.map((z) => (
          <div key={z} role="listitem" className={`zone ${ZONE_COUNT[z](d) ? "" : "zero"}`}>
            <span className="dot" style={{ background: ZONE_FILL[z] }} />
            <strong>{ZONE_LABEL[z]} · {ZONE_COUNT[z](d)}</strong>
            <span className="muted"> — {ZONE_MEANING[z]}</span>
          </div>
        ))}
      </div>
      {d.excluded_named > 0 && (
        <div className="bubble" style={{ borderLeftColor: "var(--lost)" }}>
          <h4 className="warn">{d.excluded_named} of {d.named_asked} brand answers excluded</h4>
          <p style={{ margin: ".2rem 0 .4rem" }}>
            The headline rests on {d.n_named}. An excluded answer cannot count against the brand, so this
            score is biased upward — read it as a ceiling, not a measurement.
          </p>
          <ul>{d.excluded_reasons.map((r, i) => <li key={i} className="log">{r}</li>)}</ul>
        </div>
      )}
    </>
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
  const models = [...new Set(run.answers.map((a) => a.model).filter(Boolean))].join(", ");
  return (
    <p className="source">
      <strong>{PROVENANCE_LABEL.live_api}</strong> — {models || "the configured model"} via the OpenAI
      Responses API with web search. This measures that API at this moment, not the ChatGPT consumer
      app. Answers with no search behind them are excluded from scores.
    </p>
  );
}

const TABS = [
  ["overview", "Overview"], ["win-back", "Win it back"], ["buyer", "Buyer questions"],
  ["brand", "Brand questions"], ["sources", "Sources & rivals"],
] as const;
type ReportTab = (typeof TABS)[number][0];

/** "#report-buyer" opens the Buyer questions tab, so a link can land on one. */
const tabFromHash = (): ReportTab =>
  TABS.find(([t]) => window.location.hash === `#report-${t}`)?.[0] ?? "overview";

const sortClaims = (scores: AttributeScore[]) => [...scores].sort(
  (a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.mention_rate ?? b.echo_rate ?? 0) - (a.mention_rate ?? a.echo_rate ?? 0),
);

/**
 * One run as a product: a summary pinned at the top, then one tab per question a reader asks —
 * each fitting about one screen — and a drawer with everything about a single claim. Same numbers
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
  const [claim, setClaim] = useState<string | null>(null);
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
  const opened = run.attribute_scores.find((s) => s.attribute_id === claim);
  const count: Record<ReportTab, number | undefined> = {
    overview: claims.length,
    "win-back": winBackPlan(run).actions.length,
    buyer: run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline").length,
    brand: run.probes.filter((p) => p.kind === "named" && p.phase === "baseline").length,
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
              </div>
            </div>
          </div>
          {d && <Figures d={d} />}
          {d && <PrintSummary run={run} />}
        </div>
        {d && (
          <div className="report-tabs" role="tablist" aria-label="Report sections" onKeyDown={onKey}>
            {TABS.map(([t, label]) => (
              <button key={t} id={`${uid}-tab-${t}`} role="tab" className="rtab" aria-selected={tab === t}
                      aria-controls={`${uid}-panel-${t}`} tabIndex={tab === t ? 0 : -1} onClick={() => setTab(t)}>
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
              <section>
                <h3>Claim by claim — tap one for its evidence and fix</h3>
                <ClaimCards scores={claims} onOpen={setClaim} />
              </section>
              {weightNote ? <p className="muted">{weightNote}</p>
                : onRescored && <Weights key={run.id} run={run} onRescored={onRescored} />}
              <Evidence run={run} />
            </>
          )}
          {tab === "win-back" && (
            <>
              <WinBack run={run} />
              <Section title="Where the upside is" found="the biggest open claims first">
                <GapCards scores={run.attribute_scores} onOpen={setClaim} />
              </Section>
            </>
          )}
          {tab === "buyer" && <BuyerQuestions run={run} />}
          {tab === "brand" && <BrandQuestions run={run} />}
          {tab === "sources" && (
            <>
              <CitedSources run={run} />
              <ShareOfVoice run={run} />
              <Competitors run={run} />
              <Discovered run={run} onOpen={setClaim} />
            </>
          )}
        </div>
      ) : (
        <>
          <RunSource run={run} />
          <div className="callout">This run finished without a drift report.</div>
        </>
      )}
      {opened && <ClaimDrawer s={opened} run={run} onClose={() => {
        setClaim(null);
        // Back to the card or link that opened it, which a click in Safari never focused.
        top.current?.parentElement?.querySelector<HTMLElement>(`[data-claim="${CSS.escape(opened.attribute_id)}"]`)?.focus();
      }} />}
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

/** Every claim as a card; tapping one opens its drawer. */
function ClaimCards({ scores, onOpen }: { scores: AttributeScore[]; onOpen: (id: string) => void }) {
  return (
    <div className="claim-cards">
      {sortClaims(scores).map((s) => (
        <button key={s.attribute_id} className="claim-card" data-claim={s.attribute_id} aria-haspopup="dialog" onClick={() => onOpen(s.attribute_id)}>
          <span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span>
          <strong>{s.label}</strong>
          <AiBar s={s} />
          <span className="muted">Site: {siteShare(s)}</span>
          <span className="muted">AI: {aiShare(s)}</span>
          <span className="muted">{standing(s)}</span>
        </button>
      ))}
    </div>
  );
}

/**
 * Everything about one claim: what the site says, what AI said, and its win-back fix. A native
 * modal dialog, so the browser traps focus, closes it on Esc and returns focus to the card.
 */
function ClaimDrawer({ s, run, onClose }: { s: AttributeScore; run: Run; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  // Unmounting removes the dialog, which ends the modal; closing here would fire onClose.
  useEffect(() => { if (!ref.current?.open) ref.current?.showModal(); }, []);
  const names = probeLabels(run.probes, run.topics);
  const probes = new Map(run.probes.map((p) => [p.id, p]));
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const site = (run.attributes ?? []).find((a) => a.id === s.attribute_id);
  const fix = winBackPlan(run).actions.find((a) => a.attribute_id === s.attribute_id);
  const replay = run.mode !== "live_api";
  return (
    <dialog ref={ref} className="drawer" aria-labelledby={`${s.attribute_id}-title`} onClose={onClose}
            onClick={(e) => { if (e.target === ref.current) ref.current.close(); }}>
      <div className="drawer-body">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h3 id={`${s.attribute_id}-title`} style={{ margin: 0 }}>{s.label}</h3>
            <span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span>{" "}
            <span className="muted">{standing(s)}</span>
          </div>
          <button className="ghost" onClick={() => ref.current?.close()} aria-label="Close">✕</button>
        </div>
        {s.description && <p style={{ margin: 0 }}>{s.description}</p>}
        <p style={{ margin: 0 }}><strong>{OWNER_TITLE[s.owner]}.</strong> {OWNER_TEXT[s.owner]}</p>

        <h4>What your site says</h4>
        <p className="muted" style={{ margin: 0 }}>
          {claimShare(s.claim_pages, s.claim_pages_total, s.claim_strength)
            ? `States it on ${siteShare(s)}` : siteShare(s)}
        </p>
        {site?.claim_quotes.map((q, i) => <p className="quote" key={i}>{q}</p>)}
        {!site?.claim_quotes.length && (
          <p className="muted" style={{ margin: 0 }}>
            {s.discovered ? "Nothing — found in the answers, never supplied by you or your site."
              : "No verbatim quote from your pages is saved with this run."}
          </p>
        )}

        <h4>What AI said</h4>
        <p className="muted" style={{ margin: 0 }}>
          {s.echo_rate == null ? na(s.na_reasons, "echo_rate")
            : <>Mentioned in {s.echoes} of {s.n} eligible answers · {endorsed(s)} endorsed{s.negative_echoes > 0 && ` · ${s.negative_echoes} negative`}</>}
          {s.intended_weight != null && ` · intent weight ${s.intended_weight}`}
        </p>
        {s.quotes.map((q, i) => <p className="quote" key={i}>{plain(q)}</p>)}
        {s.quotes.length === 0 && (
          <p className="muted" style={{ margin: 0 }}>
            No verbatim quote supports this attribute in any eligible answer. Absence of evidence, not
            evidence of absence — but nothing here was scored on faith.
          </p>
        )}
        {s.probe_ids.length > 0 && (
          <div className="qlist">
            {s.probe_ids.map((id) => (
              <details className="qrow" key={id}>
                <summary>
                  <span className="muted" title={id}>{names[id] ?? id}</span>
                  <span className="qrow-text">{probes.get(id)?.text ?? ""}</span>
                </summary>
                <p className="muted long-answer">
                  {answers.get(id) && replay && <span className="tag sample">sample</span>}
                  {answers.get(id) ? plain(answers.get(id)!.text) : "no answer"}
                </p>
              </details>
            ))}
          </div>
        )}
        {s.limitations.length > 0 && (
          <ul style={{ margin: 0 }}>{s.limitations.map((l, i) => <li className="warn" key={i}>{l}</li>)}</ul>
        )}

        <h4>How to win it back</h4>
        {fix ? <FixCard a={fix} run={run} />
          : <p className="muted" style={{ margin: 0 }}>
              {s.zone === "lost_claim" || s.zone === "unstated_intent"
                ? "No verified fix for this claim yet."
                : s.zone === "landed" ? "Nothing to win back: AI already says it."
                : "The action plan covers claims to win back or amplify only."}
            </p>}
        {s.owner === "authority_gap" && (
          <p className="muted" style={{ margin: 0 }}>
            Relevant capability:{" "}
            <a href="https://www.tryprofound.com/features/answer-engine-insights" target="_blank" rel="noreferrer">
              Answer Engine Insights / citation analysis
            </a>
          </p>
        )}
      </div>
    </dialog>
  );
}

function GapCard({ s, onOpen }: { s: AttributeScore; onOpen: (id: string) => void }) {
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>{s.label}</h3>
        <span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span>
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
      <button className="linky" style={{ marginTop: ".4rem" }} data-claim={s.attribute_id} aria-haspopup="dialog" onClick={() => onOpen(s.attribute_id)}>
        All evidence
      </button>
    </div>
  );
}

function GapCards({ scores, onOpen }: { scores: AttributeScore[]; onOpen: (id: string) => void }) {
  const gaps = scores
    .filter((s) => GAP_ZONES.includes(s.zone))
    .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
    .slice(0, 4);
  if (!gaps.length) {
    return <div className="card muted">No open opportunity: every claim has landed or is unweighted.</div>;
  }
  return (
    <div className="gaps">
      {gaps.map((s) => <GapCard key={s.attribute_id} s={s} onOpen={onOpen} />)}
    </div>
  );
}

/** Mirrors scoring.eligible: only an answer that counts toward the scores can name anything here. */
const counts = (a: Answer, e: QueryEvaluation) =>
  a.status === "ok" && e.valid && a.provenance !== "web_research_snapshot"
  && !(a.provenance === "live_api" && !a.search_executed);

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
      <table className="named">
        <thead>
          <tr><th>Product</th>{repeats && <th>Answers</th>}<th>Buyer topic</th><th>Where the answer names it</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
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
      {comparison && (
        <>
          <h4 className="muted" style={{ marginTop: "1rem" }}>
            Follow-up question, built from those names (exploratory — not counted in alignment)
          </h4>
          <strong>{comparison.text}</strong>
          <p className="muted long-answer">{answer ? plain(answer.text) : "no answer"}</p>
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
  const title = "Share of voice on buyer questions";
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

/** One question as a compact row; opening it shows the full answer and what the scorer made of it. */
function QuestionRow({ p, name, answer, verdict, tags, note, replay }: {
  p: Probe; name: string; answer?: Answer; verdict?: ReactNode; tags?: ReactNode; note?: ReactNode;
  replay: boolean;
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
      </div>
    </details>
  );
}

/** Buyer questions never name the company: did AI bring it up on its own? */
function BuyerQuestions({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const names = probeLabels(run.probes, run.topics);
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const evals = new Map(run.evaluations.map((e) => [e.probe_id, e]));
  const base = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  const follow = run.probes.filter((p) => p.kind === "blind" && p.phase === "followup");
  const counted = (p: Probe) => {
    const a = answers.get(p.id), e = evals.get(p.id);
    return a && e && counts(a, e) ? e : null;
  };
  const kept = base.map(counted).filter((e): e is QueryEvaluation => !!e);
  const namedIn = kept.filter((e) => e.mentioned).length;
  const recIn = kept.filter((e) => e.recommended).length;
  const excluded = base.length - kept.length;
  const verdict = (p: Probe) => {
    const e = counted(p);
    if (!e) return <span className="tag warn">excluded from scores</span>;
    if (e.recommended) return <span className="pill landed">recommended you</span>;
    if (e.negative_mention) return <span className="pill contested">criticised you</span>;
    if (e.mentioned) return <span className="pill unprioritised">named you</span>;
    return <span className="pill lost_claim">did not name you yet</span>;
  };
  const card = (p: Probe) => (
    <QuestionRow key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)}
                 verdict={verdict(p)} replay={replay}
                 note={evals.get(p.id)?.explanation && <span className="muted">{evals.get(p.id)!.explanation}</span>} />
  );
  return (
    <Section title="Buyer questions"
           found={!base.length ? na(run.drift?.na_reasons, "visibility")
             : `${base.length} asked · named you in ${namedIn}${recIn ? ` · recommended you in ${recIn}` : ""}`
               + (excluded ? ` · ${excluded} excluded` : "")}>
      <p className="muted" style={{ margin: 0 }}>
        What a buyer would ask without naming {run.profile.name}. Each one AI answered without
        bringing {run.profile.name} up is room to be found.
      </p>
      <div className="qlist">{base.map(card)}</div>
      {follow.length > 0 && (
        <>
          <h4>Follow-up questions (exploratory — not counted in the scores)</h4>
          <div className="qlist">{follow.map(card)}</div>
        </>
      )}
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
  const names = probeLabels(run.probes, run.topics);
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
            <li key={q}><span className="muted" title={q}>{names[q] ?? q}:</span> {probes.get(q)?.text}</li>
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
    <Section title="Brand questions"
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
function Discovered({ run, onOpen }: { run: Run; onOpen: (id: string) => void }) {
  const found = run.attribute_scores.filter((s) => s.discovered);
  const toShape = found.filter((s) => s.zone === "imposed").length;
  return (
    <Section title="Discovered identities"
           found={found.length ? `${found.length} found in the answers${toShape ? ` · ${toShape} to shape` : ""}`
             : "none found"}>
      {found.length ? (
        <>
          <p className="muted" style={{ margin: 0 }}>
            Found in the answers by the discovery pass — never supplied by you or your site. Each is
            an identity AI already gives {run.profile.name}: adopt it, or reframe it.
          </p>
          <ClaimCards scores={found} onOpen={onOpen} />
        </>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          The answers raised nothing about {run.profile.name} beyond the claims on the Overview.
        </p>
      )}
    </Section>
  );
}

export function Evidence({ run }: { run: Run }) {
  return (
    <details className="card">
      <summary style={{ cursor: "pointer", fontWeight: 500 }}>
        How do you know? Limitations and the workflow log
      </summary>
      <h3 style={{ marginTop: "1rem" }}>Limitations</h3>
      <ul className="muted">{run.drift?.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
      <h3>Workflow log</h3>
      <ul className="log">{run.log.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </details>
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
