import { useState } from "react";
import type { ReactNode } from "react";
import type { Answer, AttributeScore, DriftReport, Probe, QueryEvaluation, Run, RunSummary, Zone } from "./api";
import { GAP_ZONES, OWNER_TEXT, OWNER_TITLE, ZONE_ORDER, ZONES, rescoreRun } from "./api";
import { Slider } from "./claims";
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

const ZONE_COUNT: Record<Zone, (d: DriftReport) => number> = {
  landed: (d) => d.landed.length,
  lost_claim: (d) => d.lost_claims.length,
  contested: (d) => d.contested?.length ?? 0,
  unstated_intent: (d) => d.unstated_intent.length,
  imposed: (d) => d.imposed.length,
  unprioritised: (d) => d.unprioritised?.length ?? 0,
};

export function Metrics({ d, brand }: { d: DriftReport; brand: string }) {
  const h = headline(d);
  return (
    <>
      <div className="headline">
        <div className="figure potential">
          <div className="label">{h.label}</div>
          <div className="value">
            {h.potential == null ? "n/a" : `${h.potential}%`}
            {h.potential != null && <small> untapped potential</small>}
          </div>
          <div className="today">{h.today ?? d.na_reasons?.[h.field]}</div>
          <p>
            {d.lens === "claim"
              ? `Weighted by how often your site states each claim: the share of what the site says that AI’s answers about ${brand} do not yet repeat supportively.`
              : `Weighted by how much each claim matters to you: the share of what you want to be known for that AI’s answers about ${brand} do not yet say.`}
          </p>
        </div>
        <div className="figure secondary">
          <div className="label">Buyer visibility</div>
          <div className="value">{d.visibility == null ? "n/a" : d.visibility}<small>{d.visibility != null && " / 100"}</small></div>
          {d.visibility == null && <div className="today">{d.na_reasons?.visibility}</div>}
          <p>
            How often {brand} came up when a buyer asked without naming it — a mention scores half,
            a recommendation full. A separate measure; it does not move the headline.
          </p>
        </div>
      </div>
      <div className="zones" role="list" aria-label="Claims by zone">
        {ZONES.map((z) => (
          <div key={z} role="listitem" className={`zone ${ZONE_COUNT[z](d) ? "" : "zero"}`}>
            <span className="dot" style={{ background: ZONE_FILL[z] }} />
            <strong>{ZONE_LABEL[z]} · {ZONE_COUNT[z](d)}</strong>
            <span className="muted"> — {ZONE_MEANING[z]}</span>
          </div>
        ))}
      </div>
      <p className="muted" style={{ margin: 0 }}>
        {d.n_named} brand questions answered drive the headline · {d.n_blind} buyer questions answered
        drive buyer visibility · source: {provenanceLabel(d.provenance)}
      </p>
      {d.excluded_named > 0 && (
        <div className="bubble" style={{ borderLeftColor: "var(--lost)", marginTop: ".5rem", gridColumn: "auto" }}>
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

/**
 * One run, top to bottom: where it came from, the upside, claim by claim, then each kind of question
 * in its own block. `onRescored` enables the optional weights step; without it the report is read-only.
 */
export function Report({ run, onRescored }: { run: Run; onRescored?: (r: Run) => void }) {
  const d = run.drift;
  const claims = run.attribute_scores.filter((s) => !s.discovered);
  return (
    <article className="report">
      <div className="report-head">
        <div className="row">
          <Logo name={run.profile.name} url={run.profile.logo_url} />
          <h2>{run.profile.name} — report</h2>
        </div>
        <span className="muted" title={run.id}>{when(run.created_at)}</span>
      </div>
      <RunSource run={run} />
      {d ? (
        <>
          <Metrics d={d} brand={run.profile.name} />
          {onRescored && <Weights key={run.id} run={run} onRescored={onRescored} />}
          <section>
            <h3>Claim by claim: what your site says, and what AI says</h3>
            <DriftMap scores={claims} run={run} />
          </section>
          <section>
            <h3>Where the upside is</h3>
            <GapCards scores={run.attribute_scores} />
          </section>
          <div className="blocks">
            <BuyerQuestions run={run} />
            <BrandQuestions run={run} />
            <Competitors run={run} />
            <Discovered run={run} />
          </div>
          <Evidence run={run} />
        </>
      ) : (
        <div className="callout">This run finished without a drift report.</div>
      )}
    </article>
  );
}

/**
 * Intent weights on the finished run. The server re-scores the saved answers — no question is
 * re-asked and no model is called — and refuses (409) a run it cannot re-score, in its own words.
 */
function Weights({ run, onRescored }: { run: Run; onRescored: (r: Run) => void }) {
  const claims = run.attribute_scores.filter((s) => !s.discovered);
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

/** Evidence for one attribute, inline and scrollable. Beats sending the reader to the page bottom. */
function EvidenceBubble({ s, run }: { s: AttributeScore; run?: Run }) {
  const probeText = new Map((run?.probes ?? []).map((p) => [p.id, p.text]));
  const names = probeLabels(run?.probes ?? [], run?.topics ?? []);
  const share = claimShare(s.claim_pages, s.claim_pages_total, s.claim_strength);
  return (
    <div className="bubble" role="region" aria-label={`Evidence for ${s.label}`}>
      <h4>Evidence · {s.label}</h4>
      {s.description && <p style={{ margin: "0 0 .5rem" }}>{s.description}</p>}
      <dl>
        <dt>Zone</dt><dd>{ZONE_LABEL[s.zone]} — {OWNER_TITLE[s.owner]}</dd>
        <dt>How much of your site says it</dt>
        <dd>{share ? `states it on ${share}` : na(s.na_reasons, "claim_strength")}</dd>
        <dt>How often AI says it</dt>
        <dd>{s.echo_rate == null ? na(s.na_reasons, "echo_rate")
          : <>mentioned in {s.echoes} of {s.n} eligible answers · {endorsed(s)} endorsed{s.negative_echoes > 0 && ` · ${s.negative_echoes} negative`}</>}</dd>
        {s.intended_weight != null && <><dt>Intent weight</dt><dd>{s.intended_weight}</dd></>}
      </dl>
      {s.quotes.length > 0 && (
        <>
          <h4>Verbatim quotes</h4>
          {s.quotes.map((q, i) => <p className="quote" key={i}>{plain(q)}</p>)}
        </>
      )}
      {s.probe_ids.length > 0 && (
        <>
          <h4>From these questions</h4>
          <ul>
            {s.probe_ids.map((id) => (
              <li key={id} title={id}><strong>{names[id] ?? id}</strong> — {probeText.get(id) ?? ""}</li>
            ))}
          </ul>
        </>
      )}
      {s.limitations.length > 0 && (
        <>
          <h4>Limitations</h4>
          <ul>{s.limitations.map((l, i) => <li className="warn" key={i}>{l}</li>)}</ul>
        </>
      )}
      {s.quotes.length === 0 && (
        <p className="muted" style={{ margin: 0 }}>
          No verbatim quote supports this attribute in any eligible answer. Absence of evidence, not
          evidence of absence — but nothing here was scored on faith.
        </p>
      )}
    </div>
  );
}

export function DriftMap({ scores, run }: { scores: AttributeScore[]; run?: Run }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = [...scores].sort(
    (a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.mention_rate ?? b.echo_rate ?? 0) - (a.mention_rate ?? a.echo_rate ?? 0),
  );
  return (
    <div className="card">
      <div className="drift-head">
        <div>Claim</div><div>Your site says it</div><div>AI says it</div><div>Zone</div><div />
      </div>
      {rows.map((s) => (
        <div className="drift-row" key={s.attribute_id}>
          <div>
            <div>{s.label}</div>
            {s.description && <div className="muted desc">{s.description}</div>}
            <div className="muted">
              {s.discovered
                ? "discovered from the answers"
                : s.intended_weight
                  ? `intent ${s.intended_weight}`
                  : s.claim_pages > 0 || (s.claim_strength ?? 0) > 0
                    ? "on your site, not weighted"
                    : "not claimed by you"}
            </div>
          </div>
          <div>
            <div className="bar-track">
              <div className="bar" style={{ width: `${pct(s.claim_strength)}%`, background: "#8c959f" }} />
            </div>
            <div className="muted">{siteShare(s)}</div>
          </div>
          <div>
            {/* Total width is how OFTEN AI raises it. The zone-coloured segment is endorsements
                (echo_rate, what drives landed and alignment), the grey one neutral mentions, and the
                red one criticism. */}
            <div className="bar-track">
              <div className="bar" style={{ width: `${pct(s.echo_rate)}%`, background: ZONE_FILL[s.zone] }} />
              <div className="bar" style={{ width: `${Math.max(0, pct(s.mention_rate) - pct(s.echo_rate) - pct(s.negative_rate))}%`, background: "#c9d1d9" }} />
              <div className="bar neg" style={{ width: `${pct(s.negative_rate)}%` }} />
            </div>
            <div className="muted">{aiShare(s)}</div>
          </div>
          <div><span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span></div>
          <button className="info" aria-expanded={open === s.attribute_id}
                  aria-label={`Evidence for ${s.label}`}
                  onClick={() => setOpen(open === s.attribute_id ? null : s.attribute_id)}>
            Evidence
          </button>
          {open === s.attribute_id && <EvidenceBubble s={s} run={run} />}
        </div>
      ))}
    </div>
  );
}

function GapCard({ s }: { s: AttributeScore }) {
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
    </div>
  );
}

export function GapCards({ scores }: { scores: AttributeScore[] }) {
  const gaps = scores
    .filter((s) => GAP_ZONES.includes(s.zone))
    .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
    .slice(0, 4);
  if (!gaps.length) {
    return <div className="card muted">No open opportunity: every claim has landed or is unweighted.</div>;
  }
  return (
    <div className="gaps">
      {gaps.map((s) => <GapCard key={s.attribute_id} s={s} />)}
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
      <Block title={title} found="none named">
        <p className="muted" style={{ margin: 0 }}>
        {!askedBuyerQuestions
          ? "No buyer question was asked — nothing is weighted as intended — so the buyer axis was not measured and no other product could be named."
          : replay
            ? "This sample scenario names no competitor in its authored buyer answers. Replay never asks the comparison question either: that round exists only in a live run."
            : "No other product was named in any buyer answer that counts toward the scores, so there was nothing to compare against and no comparison question was asked."}
        </p>
      </Block>
    );
  }
  const top = rows[0];
  return (
    <Block title={title}
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
    </Block>
  );
}

/** One question and its answer, with what the scorer made of it. */
function QuestionCard({ p, name, answer, verdict, tags, replay }: {
  p: Probe; name: string; answer?: Answer; verdict?: ReactNode; tags?: ReactNode; replay: boolean;
}) {
  return (
    <div className="question">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <span className="muted" title={p.id}>{name}</span>
        {verdict}
      </div>
      <strong>{p.text}</strong>
      {tags && <div className="row" style={{ flexWrap: "wrap", gap: ".3rem" }}>{tags}</div>}
      <p className="muted long-answer">
        {answer && replay && <span className="tag sample">sample</span>}
        {answer ? plain(answer.text) : "no answer"}
      </p>
    </div>
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
    <QuestionCard key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)}
                  verdict={verdict(p)} replay={replay}
                  tags={evals.get(p.id)?.explanation && <span className="muted">{evals.get(p.id)!.explanation}</span>} />
  );
  return (
    <Block title="Buyer questions"
           found={!base.length ? na(run.drift?.na_reasons, "visibility")
             : `${base.length} asked · named you in ${namedIn}${recIn ? ` · recommended you in ${recIn}` : ""}`
               + (excluded ? ` · ${excluded} excluded` : "")}>
      <p className="muted" style={{ margin: 0 }}>
        What a buyer would ask without naming {run.profile.name}. Each one AI answered without
        bringing {run.profile.name} up is room to be found.
      </p>
      <div className="questions">{base.map(card)}</div>
      {follow.length > 0 && (
        <>
          <h4>Follow-up questions (exploratory — not counted in the scores)</h4>
          <div className="questions">{follow.map(card)}</div>
        </>
      )}
    </Block>
  );
}

/** Brand questions name the company and never a claim: what does AI say it is known for? */
function BrandQuestions({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const names = probeLabels(run.probes, run.topics);
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const raised = new Map<string, AttributeScore[]>();
  for (const s of run.attribute_scores) {
    for (const id of s.probe_ids) raised.set(id, [...(raised.get(id) ?? []), s]);
  }
  const named = run.probes.filter((p) => p.kind === "named" && p.phase === "baseline");
  const withClaims = named.filter((p) => raised.get(p.id)?.some((s) => !s.discovered)).length;
  const d = run.drift;
  return (
    <Block title="Brand questions"
           found={`${named.length} asked · your claims came up in ${withClaims}`
             + (d?.excluded_named ? ` · ${d.excluded_named} excluded` : "")}>
      <p className="muted" style={{ margin: 0 }}>
        Each names {run.profile.name} and never a claim, so whatever AI says it is known for, it said
        unprompted. These answers drive the headline.
      </p>
      <div className="questions">
        {named.map((p) => (
          <QuestionCard key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)} replay={replay}
                        verdict={answers.get(p.id)?.status !== "ok"
                          ? <span className="tag warn">no answer — excluded</span> : undefined}
                        tags={(raised.get(p.id) ?? []).map((s) => (
                          <span key={s.attribute_id} className={`pill ${s.zone}`}>{s.label}</span>
                        ))} />
        ))}
      </div>
    </Block>
  );
}

/** Things AI says the company is known for that neither the company nor its site ever supplied. */
function Discovered({ run }: { run: Run }) {
  const found = run.attribute_scores.filter((s) => s.discovered);
  const toShape = found.filter((s) => s.zone === "imposed").length;
  return (
    <Block title="Discovered identities"
           found={found.length ? `${found.length} found in the answers${toShape ? ` · ${toShape} to shape` : ""}`
             : "none found"}>
      {found.length ? (
        <>
          <p className="muted" style={{ margin: 0 }}>
            Found in the answers by the discovery pass — never supplied by you or your site. Each is
            an identity AI already gives {run.profile.name}: adopt it, or reframe it.
          </p>
          <DriftMap scores={found} run={run} />
        </>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          The answers raised nothing about {run.profile.name} beyond the claims above.
        </p>
      )}
    </Block>
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
