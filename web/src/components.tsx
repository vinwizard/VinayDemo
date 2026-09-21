import { useState } from "react";
import type { AttributeScore, DriftReport, Run, RunSummary } from "./api";
import { OWNER_TEXT, OWNER_TITLE, ZONE_LABEL, ZONE_ORDER } from "./api";
import { probeLabels, provenanceLabel, runLabels, statedOn } from "./labels";

const ZONE_FILL: Record<string, string> = {
  landed: "var(--landed)",
  lost_claim: "var(--lost)",
  contested: "var(--contested)",
  unstated_intent: "var(--unstated)",
  imposed: "var(--imposed)",
};

const pct = (x: number | null) => (x == null ? 0 : Math.round(x * 100));

export function Metrics({ d }: { d: DriftReport }) {
  return (
    <>
      <div className="metrics">
        <div className="metric">
          <div className="label">Positioning alignment</div>
          <div className="value">{d.alignment == null ? "n/a" : `${d.alignment}%`}</div>
        </div>
        <div className="metric"><div className="label">Landed</div><div className="value">{d.landed.length}</div></div>
        <div className="metric"><div className="label">Lost claims</div><div className="value">{d.lost_claims.length}</div></div>
        <div className="metric"><div className="label">Contested</div><div className="value">{d.contested?.length ?? 0}</div></div>
        <div className="metric"><div className="label">Never stated</div><div className="value">{d.unstated_intent.length}</div></div>
        <div className="metric"><div className="label">Imposed</div><div className="value">{d.imposed.length}</div></div>
      </div>
      <p className="muted" style={{ marginTop: ".4rem" }}>
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

/** Evidence for one attribute, inline and scrollable. Beats sending the reader to the page bottom. */
function EvidenceBubble({ s, run }: { s: AttributeScore; run?: Run }) {
  const probeText = new Map((run?.probes ?? []).map((p) => [p.id, p.text]));
  const names = probeLabels(run?.probes ?? [], run?.topics ?? []);
  return (
    <div className="bubble" role="region" aria-label={`Evidence for ${s.label}`}>
      <h4>Evidence · {s.label}</h4>
      {s.description && <p style={{ margin: "0 0 .5rem" }}>{s.description}</p>}
      <dl>
        <dt>Zone</dt><dd>{ZONE_LABEL[s.zone]} — {OWNER_TITLE[s.owner]}</dd>
        <dt>How much of your site says it</dt>
        <dd>{s.claim_pages_total ? `states it on ${statedOn(s.claim_pages, s.claim_pages_total)}` : "no page data"}</dd>
        <dt>How often AI says it</dt>
        <dd>{s.echoes} of {s.n} eligible answers{s.negative_echoes > 0 && ` · ${s.negative_echoes} negative`}</dd>
        {s.intended_weight != null && <><dt>Intent weight</dt><dd>{s.intended_weight}</dd></>}
      </dl>
      {s.quotes.length > 0 && (
        <>
          <h4>Verbatim quotes</h4>
          {s.quotes.map((q, i) => <p className="quote" key={i}>{q}</p>)}
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
        <div>Attribute</div><div>What you claim</div><div>What AI says</div><div /><div />
      </div>
      {rows.map((s) => (
        <div className="drift-row" key={s.attribute_id}>
          <div>
            <div>{s.label}</div>
            {s.description && <div className="muted desc">{s.description}</div>}
            <div className="muted">
              {s.intended_weight ? `intent ${s.intended_weight}` : "not claimed by you"}
            </div>
          </div>
          <div>
            <div className="bar-track">
              <div className="bar" style={{ width: `${pct(s.claim_strength)}%`, background: "#8c959f" }} />
            </div>
            <div className="muted">{statedOn(s.claim_pages, s.claim_pages_total)}</div>
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
            i
          </button>
          {open === s.attribute_id && <EvidenceBubble s={s} run={run} />}
        </div>
      ))}
    </div>
  );
}

export function GapCards({ scores }: { scores: AttributeScore[] }) {
  const gaps = scores
    .filter((s) => s.zone !== "landed")
    .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
    .slice(0, 4);
  if (!gaps.length) return null;
  return (
    <div className="stack">
      {gaps.map((s) => (
        <div className="card" key={s.attribute_id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3>{s.label}</h3>
            <span className={`pill ${s.zone}`}>{OWNER_TITLE[s.owner]}</span>
          </div>
          <p style={{ margin: ".4rem 0 0" }}>{OWNER_TEXT[s.owner]}</p>
          <p className="muted" style={{ margin: ".3rem 0 0" }}>
            {s.claim_pages_total ? `${statedOn(s.claim_pages, s.claim_pages_total)} state it` : "no page data"}
            {" · "}AI echoed it in {s.echoes} of {s.n} brand answers
            {s.negative_echoes > 0 && ` · ${s.negative_echoes} negative`}
          </p>
          {s.quotes[0] && <p className="quote">{s.quotes[0]}</p>}
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
      ))}
    </div>
  );
}

/**
 * Who AI offered instead, and what it said when asked to compare.
 *
 * Nobody supplied these names: a buyer question describes what the company does without naming it,
 * so every brand in the answer is one the model chose. The engine has always extracted them and
 * checked them verbatim against the answer text; until now nothing displayed them.
 */
export function Competitors({ run }: { run: Run }) {
  const byTopic = new Map(run.topics.map((t) => [t.id, t.label]));
  const rows = run.topic_evaluations
    .filter((te) => te.phase === "baseline" && te.top_competitors.length > 0)
    .map((te) => ({ topic: byTopic.get(te.topic_id) ?? te.topic_id, names: te.top_competitors }));
  const comparison = run.probes.find((p) => p.kind === "named" && p.phase === "followup");
  const answer = comparison && run.answers.find((a) => a.probe_id === comparison.id);
  // "Nobody was named" and "nobody was asked" are different findings. With no weighted claim there
  // are no buyer questions at all, and an empty competitor set then means silence, not absence.
  const askedBuyerQuestions = run.probes.some((p) => p.kind === "blind" && p.phase === "baseline");
  if (!rows.length) {
    return (
      <div className="card muted">
        {askedBuyerQuestions
          ? "No competitor was named in any buyer answer, so there was nothing to compare against and no comparison question was asked."
          : "No buyer question was asked — nothing is weighted as intended — so the buyer axis was not measured and no competitor could be discovered."}
      </div>
    );
  }
  return (
    <div className="card">
      <h3>Who AI named instead</h3>
      <p className="muted" style={{ margin: ".3rem 0 .6rem" }}>
        Discovered, not asked for: these are the brands the model volunteered when a buyer described
        what you do without naming you.
      </p>
      <table>
        <thead><tr><th>Buyer topic</th><th>Recommended instead</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.topic}><td>{r.topic}</td><td>{r.names.join(", ")}</td></tr>
          ))}
        </tbody>
      </table>
      {comparison && (
        <>
          <h4 className="muted" style={{ marginTop: "1rem" }}>
            Follow-up question, built from those names (exploratory — not counted in alignment)
          </h4>
          <strong>{comparison.text}</strong>
          <p className="muted" style={{ marginBottom: 0 }}>{answer?.text ?? "no answer"}</p>
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
            <p className="muted" style={{ marginBottom: 0 }}>{byId[p.id]?.text ?? "no answer"}</p>
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
