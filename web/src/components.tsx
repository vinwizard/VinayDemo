import type { AttributeScore, DriftReport, Run, RunSummary } from "./api";
import { OWNER_TEXT, OWNER_TITLE, ZONE_LABEL, ZONE_ORDER } from "./api";

const ZONE_FILL: Record<string, string> = {
  landed: "var(--landed)",
  lost_claim: "var(--lost)",
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
        <div className="metric"><div className="label">Never stated</div><div className="value">{d.unstated_intent.length}</div></div>
        <div className="metric"><div className="label">Imposed</div><div className="value">{d.imposed.length}</div></div>
      </div>
      <p className="muted" style={{ marginTop: ".4rem" }}>
        {d.n_named} named answers drive perception · {d.n_blind} blind answers give a separate visibility
        score of {d.visibility == null ? "n/a" : `${d.visibility}/100`} · provenance {d.provenance}
      </p>
    </>
  );
}

export function DriftMap({ scores }: { scores: AttributeScore[] }) {
  const rows = [...scores].sort(
    (a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.echo_rate ?? 0) - (a.echo_rate ?? 0),
  );
  return (
    <div className="card">
      <div className="drift-head">
        <div>Attribute</div><div>What you claim</div><div>What AI says</div><div />
      </div>
      {rows.map((s) => (
        <div className="drift-row" key={s.attribute_id}>
          <div>
            <div>{s.label}</div>
            <div className="muted">
              {s.intended_weight ? `intent ${s.intended_weight}` : "not claimed by you"}
            </div>
          </div>
          <div>
            <div className="bar-track">
              <div className="bar" style={{ width: `${pct(s.claim_strength)}%`, background: "#8c959f" }} />
            </div>
            <div className="muted">{pct(s.claim_strength)}% of pages</div>
          </div>
          <div>
            <div className="bar-track">
              <div className="bar" style={{ width: `${pct(s.echo_rate)}%`, background: ZONE_FILL[s.zone] }} />
            </div>
            <div className="muted">{s.echoes}/{s.n} answers</div>
          </div>
          <div><span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span></div>
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
            {s.claim_strength == null ? "no page data" : `${pct(s.claim_strength)}% of your known pages state it`}
            {" · "}AI echoed it in {s.echoes} of {s.n} named answers
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

export function Evidence({ run }: { run: Run }) {
  const named = run.probes.filter((p) => p.kind === "named");
  const byId = Object.fromEntries(run.answers.map((a) => [a.probe_id, a]));
  return (
    <details className="card">
      <summary style={{ cursor: "pointer", fontWeight: 500 }}>
        How do you know? Evidence, limitations and the full run
      </summary>
      <h3 style={{ marginTop: "1rem" }}>Limitations</h3>
      <ul className="muted">{run.drift?.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
      <h3>Named questions asked (never contain an attribute name)</h3>
      <div className="stack">
        {named.map((p) => (
          <div className="card" key={p.id}>
            <div className="log">{p.id}</div>
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

export function Compare({ a, b }: { a: Run; b: Run }) {
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
            <div className="muted">A · scenario {a.scenario} · {a.id}</div>
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
            <div className="muted">B · scenario {b.scenario} · {b.id}</div>
            <div className="value" style={{ fontSize: "1.6rem", fontWeight: 600 }}>
              {db?.alignment ?? "n/a"}%
            </div>
          </div>
        </div>
      </div>
      <div className="card">
        <div className="cmp muted" style={{ borderTop: "none" }}>
          <div>Attribute</div><div>A</div><div>B</div><div>Zone change</div>
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
              <td className="log">{r.id}</td>
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
