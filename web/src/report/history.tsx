import type { RunSummary } from "../api";
import { PROVENANCE_LABEL, headline, potentialText, runLabels } from "../labels";
import { Term } from "../popover";

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
