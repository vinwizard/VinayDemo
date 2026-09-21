import { useCallback, useEffect, useState } from "react";
import type { CompanyDetail, Health, Run, RunSummary } from "./api";
import { API, getCompany, getHealth, getRun, getRuns } from "./api";
import { Compare, History, Logo, Report } from "./components";
import { headline, potentialText, runLabels } from "./labels";
import { CompanyWorkflow } from "./workflow";

type Tab = "preloaded" | "onboard" | "history" | "compare";

export default function App() {
  const [tab, setTab] = useState<Tab>("preloaded");
  const [health, setHealth] = useState<Health | null>(null);
  const [seed, setSeed] = useState<CompanyDetail["profile"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [opened, setOpened] = useState<Run | null>(null);
  const [cmpA, setCmpA] = useState(""), [cmpB, setCmpB] = useState("");
  const [pairA, setPairA] = useState<Run | null>(null), [pairB, setPairB] = useState<Run | null>(null);

  const refreshRuns = useCallback(() => { getRuns().then(setRuns).catch(() => {}); }, []);

  useEffect(() => {
    getHealth().then((h) => {
      setHealth(h);
      getCompany(h.seed_company).then((c) => setSeed(c.profile)).catch(() => {});
    })
      .catch(() => setError(`Could not reach the API at ${API}. Start it first — see WEB.md.`));
    refreshRuns();
  }, [refreshRuns]);

  const openRun = (id: string) => { getRun(id).then(setOpened).catch((e) => setError(String(e))); };

  useEffect(() => {
    if (cmpA) getRun(cmpA).then(setPairA).catch(() => setPairA(null));
    if (cmpB) getRun(cmpB).then(setPairB).catch(() => setPairB(null));
  }, [cmpA, cmpB]);

  const runNames = runLabels(runs);
  const tabs: [Tab, string][] = [
    ["preloaded", seed?.name ?? "Notion"], ["onboard", "Onboard your own company"],
    ["history", "History"], ["compare", "Compare"],
  ].filter(([t]) => !(health?.public_demo && t === "onboard")) as [Tab, string][];

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>Positioning Drift</h1>
          <p className="sub">How different is your brand in AI answers from the brand you are trying to be?</p>
        </div>
        <nav className="tabs" role="tablist">
          {tabs.map(([t, label]) => (
            <button key={t} role="tab" className="tab" aria-selected={tab === t}
                    onClick={() => { setTab(t); if (t === "history") setOpened(null); }}>
              {t === "preloaded" && seed && <Logo name={seed.name} url={seed.logo_url} size={18} />}
              {label}
            </button>
          ))}
        </nav>
      </header>

      {health?.public_demo && (
        <div className="callout warn-box">
          <strong>Public demo — saved replay only.</strong> Every answer here is a bundled sample, not a
          live measurement, and no AI model is called. Onboarding and live runs need your own key:
          clone the repo and run it locally.
        </div>
      )}
      {error && <div className="callout error">{error}</div>}

      {/* Both company tabs stay mounted, so a measurement keeps streaming while you look elsewhere. */}
      <div hidden={tab !== "preloaded"}>
        {health && <CompanyWorkflow companyId={health.seed_company} preloaded onRunSaved={refreshRuns} />}
      </div>
      <div hidden={tab !== "onboard"}>
        {health && !health.live_available && (
          <div className="callout warn-box">
            No API key is configured on the server, so reading a site and measuring it will fail.
            Put <code>OPENAI_API_KEY</code> in <code>.env</code> and restart the API.
          </div>
        )}
        <CompanyWorkflow onRunSaved={refreshRuns} />
      </div>

      {tab === "history" && (opened ? (
        <div className="stack">
          <button className="linky back" onClick={() => setOpened(null)}>← All runs</button>
          <Report run={opened} onRescored={(r) => { setOpened(r); refreshRuns(); }} />
        </div>
      ) : <History runs={runs} onOpen={openRun} />)}

      {tab === "compare" && (
        <div className="stack">
          <div className="card row" style={{ gap: "1rem", flexWrap: "wrap" }}>
            <label className="muted">Run A</label>
            <select value={cmpA} onChange={(e) => setCmpA(e.target.value)}>
              <option value="">choose…</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {runNames[r.id]?.full ?? r.id} · {headline(r).label} · {potentialText(headline(r))}
                </option>
              ))}
            </select>
            <label className="muted">Run B</label>
            <select value={cmpB} onChange={(e) => setCmpB(e.target.value)}>
              <option value="">choose…</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {runNames[r.id]?.full ?? r.id} · {headline(r).label} · {potentialText(headline(r))}
                </option>
              ))}
            </select>
          </div>
          {pairA && pairB ? <Compare a={pairA} b={pairB} runs={runs} />
            : <div className="card muted">Pick two runs to compare. Measure a company twice if the list is short.</div>}
        </div>
      )}

      <footer className="foot">Independent portfolio demo — not a Profound product or integration.</footer>
    </div>
  );
}
