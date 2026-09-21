import { useState } from "react";
import type { Answer, AttributeScore, DriftReport, QueryEvaluation, Run, RunSummary, Zone } from "./api";
import { GAP_ZONES, OWNER_TEXT, OWNER_TITLE, ZONE_LABEL, ZONE_MEANING, ZONE_ORDER, ZONES } from "./api";
import { PROVENANCE_LABEL, claimShare, plain, probeLabels, provenanceLabel, runLabels, when } from "./labels";

const ZONE_FILL: Record<Zone, string> = {
  landed: "var(--landed)",
  lost_claim: "var(--lost)",
  contested: "var(--contested)",
  unstated_intent: "var(--unstated)",
  imposed: "var(--imposed)",
  unprioritised: "var(--unprioritised)",
};

const pct = (x: number | null) => (x == null ? 0 : Math.round(x * 100));

const ZONE_COUNT: Record<Zone, (d: DriftReport) => number> = {
  landed: (d) => d.landed.length,
  lost_claim: (d) => d.lost_claims.length,
  contested: (d) => d.contested?.length ?? 0,
  unstated_intent: (d) => d.unstated_intent.length,
  imposed: (d) => d.imposed.length,
  unprioritised: (d) => d.unprioritised?.length ?? 0,
};

export function Metrics({ d, brand }: { d: DriftReport; brand: string }) {
  return (
    <>
      <div className="headline">
        <div className="figure">
          <div className="label">Positioning alignment</div>
          <div className="value">{d.alignment == null ? "n/a" : `${d.alignment}%`}</div>
          <p>
            Weighted by how much each claim matters to you: how often AI’s answers about {brand} say
            what you want to be known for.
            {d.alignment == null && " Withheld — too few brand answers to score."}
          </p>
        </div>
        <div className="figure secondary">
          <div className="label">Buyer visibility</div>
          <div className="value">{d.visibility == null ? "n/a" : d.visibility}<small>{d.visibility != null && " / 100"}</small></div>
          <p>
            How often {brand} came up when a buyer asked without naming it — a mention scores half,
            a recommendation full. A separate measure; it does not move alignment.
          </p>
        </div>
      </div>
      <div className="zones" role="list" aria-label="Claims by zone">
        {ZONES.map((z) => (
          <div key={z} role="listitem" className={`zone ${ZONE_COUNT[z](d) ? "" : "zero"}`}>
            <span className="dot" style={{ background: ZONE_FILL[z] }} />
            <strong>{ZONE_COUNT[z](d)} {ZONE_LABEL[z]}</strong>
            <span className="muted"> — {ZONE_MEANING[z]}</span>
          </div>
        ))}
      </div>
      <p className="muted" style={{ margin: 0 }}>
        {d.n_named} brand questions answered drive perception · {d.n_blind} buyer questions answered
        give a separate visibility score of {d.visibility == null ? "n/a" : `${d.visibility}/100`} ·
        source: {provenanceLabel(d.provenance)}
      </p>
      {d.excluded_named > 0 && (
        <div className="bubble" style={{ borderLeftColor: "var(--lost)", marginTop: ".5rem", gridColumn: "auto" }}>
          <h4 className="warn">{d.excluded_named} of {d.named_asked} brand answers excluded</h4>
          <p style={{ margin: ".2rem 0 .4rem" }}>
            Alignment rests on {d.n_named}. An excluded answer cannot count against the brand, so this
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

/** One run, top to bottom: where it came from, the two numbers, then claim by claim, then why. */
export function Report({ run }: { run: Run }) {
  const d = run.drift;
  return (
    <article className="report">
      <div className="report-head">
        <h2>{run.profile.name} — report</h2>
        <span className="muted" title={run.id}>{when(run.created_at)}</span>
      </div>
      <RunSource run={run} />
      {d ? (
        <>
          <Metrics d={d} brand={run.profile.name} />
          <section>
            <h3>Claim by claim: what your site says, and what AI says</h3>
            <DriftMap scores={run.attribute_scores} run={run} />
          </section>
          <section>
            <h3>Whose problem is each gap?</h3>
            <GapCards scores={run.attribute_scores} />
          </section>
          <Competitors run={run} />
          <Evidence run={run} />
        </>
      ) : (
        <div className="callout">This run finished without a drift report.</div>
      )}
    </article>
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
        <dd>{share ? `states it on ${share}` : "no page data"}</dd>
        <dt>How often AI says it</dt>
        <dd>{s.echoes} of {s.n} eligible answers{s.negative_echoes > 0 && ` · ${s.negative_echoes} negative`}</dd>
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
              {s.intended_weight
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
            <div className="muted">
              {claimShare(s.claim_pages, s.claim_pages_total, s.claim_strength) ?? "no page data"}
            </div>
          </div>
          <div>
            {/* Width is how OFTEN AI raises it; the red segment is how much of that was criticism.
                Using echo_rate alone would draw a zero-width bar for an attribute AI only attacks. */}
            <div className="bar-track">
              <div className="bar" style={{ width: `${pct(s.echo_rate)}%`, background: ZONE_FILL[s.zone] }} />
              <div className="bar neg" style={{ width: `${pct(s.negative_rate)}%` }} />
            </div>
            <div className="muted">
              {s.echoes}/{s.n} answers{s.negative_echoes > 0 && ` · ${s.negative_echoes} negative`}
            </div>
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
  const share = claimShare(s.claim_pages, s.claim_pages_total, s.claim_strength);
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>{s.label}</h3>
        <span className={`pill ${s.zone}`}>{OWNER_TITLE[s.owner]}</span>
      </div>
      <p style={{ margin: ".4rem 0 0" }}>{OWNER_TEXT[s.owner]}</p>
      <p className="muted" style={{ margin: ".3rem 0 0" }}>
        {share ? `${share} state it` : "no page data"}
        {" · "}AI echoed it in {s.echoes} of {s.n} brand answers
        {s.negative_echoes > 0 && ` · ${s.negative_echoes} negative`}
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
    return <div className="card muted">Nothing to fix: no claim is lost, contested, understated or imposed.</div>;
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
  if (!rows.length) {
    return (
      <div className="card muted">
        {!askedBuyerQuestions
          ? "No buyer question was asked — nothing is weighted as intended — so the buyer axis was not measured and no other product could be named."
          : replay
            ? "This sample scenario names no competitor in its authored buyer answers. Replay never asks the comparison question either: that round exists only in a live run."
            : "No other product was named in any buyer answer that counts toward the scores, so there was nothing to compare against and no comparison question was asked."}
      </div>
    );
  }
  return (
    <div className="card">
      <h3>Named in buyer answers</h3>
      <p className="muted" style={{ margin: ".3rem 0 .6rem" }}>
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
    </div>
  );
}

export function Evidence({ run }: { run: Run }) {
  const named = run.probes.filter((p) => p.kind === "named");
  const byId = Object.fromEntries(run.answers.map((a) => [a.probe_id, a]));
  const names = probeLabels(run.probes, run.topics);
  return (
    <details className="card">
      <summary style={{ cursor: "pointer", fontWeight: 500 }}>
        How do you know? Evidence, limitations and the full run
      </summary>
      <h3 style={{ marginTop: "1rem" }}>Limitations</h3>
      <ul className="muted">{run.drift?.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
      <h3>Brand questions asked (never contain an attribute name)</h3>
      <div className="stack">
        {named.map((p) => (
          <div className="card" key={p.id}>
            <div className="muted" title={p.id}>{names[p.id] ?? p.id}</div>
            <strong>{p.text}</strong>
            <p className="muted long-answer">{byId[p.id] ? plain(byId[p.id].text) : "no answer"}</p>
          </div>
        ))}
      </div>
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
  const da = a.drift, db = b.drift;
  const delta = (x: number | null | undefined, y: number | null | undefined) =>
    x == null || y == null ? null : Math.round((y - x) * 10) / 10;
  const alignDelta = delta(da?.alignment, db?.alignment);
  return (
    <div className="stack">
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="muted" title={a.id}>{name(a)}</div>
            <div className="value" style={{ fontSize: "1.6rem", fontWeight: 600 }}>
              {da?.alignment ?? "n/a"}%
            </div>
          </div>
          <div style={{ textAlign: "center" }}>
            <div className="muted">change</div>
            <div className={`value ${alignDelta == null ? "" : alignDelta >= 0 ? "delta up" : "delta down"}`}
                 style={{ fontSize: "1.6rem", fontWeight: 600 }}>
              {alignDelta == null ? "—" : `${alignDelta > 0 ? "+" : ""}${alignDelta}`}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="muted" title={b.id}>{name(b)}</div>
            <div className="value" style={{ fontSize: "1.6rem", fontWeight: 600 }}>
              {db?.alignment ?? "n/a"}%
            </div>
          </div>
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
              <div>{sa ? <span className={`pill ${sa.zone}`}>{pct(sa.echo_rate)}%</span> : <span className="muted">—</span>}</div>
              <div>{sb ? <span className={`pill ${sb.zone}`}>{pct(sb.echo_rate)}%</span> : <span className="muted">—</span>}</div>
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
          <tr><th>Run</th><th>When</th><th>Scenario</th><th>Alignment</th><th>Landed</th><th>Lost</th><th>Imposed</th></tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="pick" onClick={() => onOpen(r.id)}>
              <td title={r.id}>{names[r.id]?.short ?? r.id}</td>
              <td className="muted">{r.created_at.replace("T", " ")}</td>
              <td>{r.scenario ?? "—"}</td>
              <td><strong>{r.alignment == null ? "n/a" : `${r.alignment}%`}</strong></td>
              <td>{r.landed}</td><td>{r.lost}</td><td>{r.imposed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
