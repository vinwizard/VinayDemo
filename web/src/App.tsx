import { useCallback, useEffect, useRef, useState } from "react";
import type { CompanyDetail, Health, Run, RunSummary, Scenario } from "./api";
import { getHealth, getRun, getRuns, getScenarios, streamRun } from "./api";
import { Compare, Competitors, DriftMap, Evidence, GapCards, History, Metrics } from "./components";
import { PROBE_KIND_LABEL, runLabels, statedOn, streamingProbeLabel } from "./labels";
import { Onboard } from "./onboard";

type Tab = "measure" | "onboard" | "report" | "history" | "compare";
interface FeedItem { key: string; text: string; sub?: string }

export default function App() {
  const [tab, setTab] = useState<Tab>("measure");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState("A");
  const [mode, setMode] = useState<"demo" | "live">("demo");
  const [health, setHealth] = useState<Health | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [progress, setProgress] = useState({ done: 0, expected: 0 });
  const [error, setError] = useState<string | null>(null);
  const [companyRun, setCompanyRun] = useState<CompanyDetail | null>(null);
  const [cmpA, setCmpA] = useState(""), [cmpB, setCmpB] = useState("");
  const [pairA, setPairA] = useState<Run | null>(null), [pairB, setPairB] = useState<Run | null>(null);
  const closer = useRef<(() => void) | null>(null);

  const refreshRuns = useCallback(() => { getRuns().then(setRuns).catch(() => {}); }, []);

  useEffect(() => {
    getScenarios().then(setScenarios).catch((e) => setError(String(e)));
    getHealth().then(setHealth).catch(() => {});
    refreshRuns();
    return () => closer.current?.(); // abort an in-flight stream if the app unmounts
  }, [refreshRuns]);

  const startRun = (target: { scenario: string } | { company: string }, runMode: "demo" | "live") => {
    setBusy(true); setFeed([]); setError(null); setProgress({ done: 0, expected: 0 });
    closer.current?.();
    closer.current = streamRun(target, runMode, {
      onNode: (e) =>
        setFeed((f) => [{ key: `n${f.length}`, text: `${e.stage} · ${e.agent}`, sub: e.log }, ...f]),
      onAnswer: (e) => {
        setProgress({ done: e.done, expected: e.expected });
        setFeed((f) => [{
          key: `a${f.length}`,
          text: `${e.done}/${e.expected} · ${streamingProbeLabel(e.probe_id, e.kind, e.phase, e.topic_label)}`
                + ` · ${PROBE_KIND_LABEL[e.kind] ?? e.kind}`,
          sub: e.text,
        }, ...f]);
      },
      onDone: (e) => { setRun(e.run); setBusy(false); setTab("report"); refreshRuns(); },
      onError: (e) => { setError(e.message); setBusy(false); },
    });
  };

  const measure = () => { setCompanyRun(null); startRun({ scenario }, mode); };
  // An onboarded company has no authored answers, so it is always a live measurement — and the
  // banner has to say so, or real paid calls stream in under the synthetic-demo label.
  const measureCompany = (c: CompanyDetail) => {
    setCompanyRun(c); setMode("live"); setTab("measure"); startRun({ company: c.id }, "live");
  };

  const openRun = (id: string) => { getRun(id).then((r) => { setRun(r); setTab("report"); }).catch((e) => setError(String(e))); };

  useEffect(() => {
    if (cmpA) getRun(cmpA).then(setPairA).catch(() => setPairA(null));
    if (cmpB) getRun(cmpB).then(setPairB).catch(() => setPairB(null));
  }, [cmpA, cmpB]);

  const sc = scenarios.find((s) => s.id === scenario);
  const runNames = runLabels(runs);
  const pctDone = progress.expected ? (progress.done / progress.expected) * 100 : 0;

  return (
    <div className="shell">
      <div className="topbar">
        <h1>Positioning Drift</h1>
        <span className="sub">How different is your brand in AI answers from the brand you are trying to be?</span>
      </div>

      <div className="banner">
        {mode === "live" ? (
          <>
            <strong>LIVE MODE — real calls to {health?.measured_model ?? "the configured model"} via
            the OpenAI Responses API with web search.</strong>
            <br />This measures that API at this moment, not the ChatGPT consumer app. Answers with no
            search behind them are excluded from scores. Calls cost money.
          </>
        ) : (
          <>
            <strong>SYNTHETIC DEMO — fixture replay; no live chatbot measurements; model judgment simulated.</strong>
            <br />Independent portfolio demo — not a Profound product or integration.
          </>
        )}
      </div>

      <div className="tabs" role="tablist">
        {(["measure", "onboard", "report", "history", "compare"] as Tab[]).map((t) => (
          <button key={t} role="tab" className="tab" aria-selected={tab === t}
                  onClick={() => setTab(t)} disabled={t === "report" && !run}>
            {t === "measure" ? "Measure" : t === "onboard" ? "Onboard a company"
              : t === "report" ? "Report" : t === "history" ? "History" : "Compare"}
          </button>
        ))}
      </div>

      {error && <div className="card" style={{ borderColor: "var(--lost)", color: "var(--lost)" }}>{error}</div>}

      {tab === "measure" && (
        <div className="stack">
          <div className="card">
            <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <div className="row">
                <label className="muted" htmlFor="sc">Scenario</label>
                <select id="sc" value={scenario} onChange={(e) => setScenario(e.target.value)} disabled={busy}>
                  {scenarios.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
                </select>
              </div>
              <div className="row">
                <label className="muted" htmlFor="md">Mode</label>
                <select id="md" value={mode} disabled={busy}
                        onChange={(e) => setMode(e.target.value as "demo" | "live")}>
                  <option value="demo">Demo replay (synthetic)</option>
                  <option value="live" disabled={!health?.live_available}>
                    {health?.live_available
                      ? `Live — ${health.measured_model}`
                      : "Live (no API key configured)"}
                  </option>
                </select>
                <button className="primary" onClick={measure} disabled={busy}>
                  {busy ? "Measuring…" : mode === "live" ? "Run live measurement" : "Measure drift"}
                </button>
              </div>
            </div>
            {companyRun ? (
              <>
                <h3 style={{ marginTop: "1.1rem" }}>
                  Measuring {companyRun.profile.name} — onboarded from {companyRun.profile.domain}
                </h3>
                <p className="muted" style={{ marginBottom: 0 }}>
                  A real company has no authored answers, so this is always a live measurement. The
                  scenario above belongs to the bundled demos and is not part of this run.
                </p>
              </>
            ) : sc && (
              <>
                <h3 style={{ marginTop: "1.1rem" }}>{sc.company} wants to be known for</h3>
                <div className="stack" style={{ marginTop: ".5rem" }}>
                  {sc.intended.map((a) => (
                    <div key={a.id}>
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <span>{a.label}</span>
                        <span className="muted">
                          intent {a.weight} · stated on {statedOn(a.claim_pages, a.claim_pages_total)}
                        </span>
                      </div>
                      {a.description && <div className="muted desc">{a.description}</div>}
                    </div>
                  ))}
                </div>
                <p className="muted" style={{ marginBottom: 0 }}>
                  Asks {sc.named_probes} brand questions that name the brand but never name an attribute
                  {mode === "live"
                    ? ". Live runs measure perception only, so no visibility score is produced."
                    : ", plus 12 buyer questions that never name the brand."}
                </p>
              </>
            )}
          </div>

          {(busy || feed.length > 0) && (
            <div className="card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h3>Live workflow</h3>
                <span className="muted">{progress.done}/{progress.expected || "?"} answers</span>
              </div>
              <div className="progress" style={{ margin: ".6rem 0 .9rem" }}>
                <div style={{ width: `${pctDone}%` }} />
              </div>
              <div className="feed">
                {feed.map((f) => (
                  <div key={f.key}>
                    <div className="log">{f.text}</div>
                    {f.sub && <div className="muted" style={{ marginTop: "-.15rem" }}>{f.sub}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "onboard" && (
        <Onboard liveAvailable={!!health?.live_available} busy={busy} onMeasure={measureCompany} />
      )}

      {tab === "report" && run?.drift && (
        <div className="stack">
          <Metrics d={run.drift} />
          <DriftMap scores={run.attribute_scores} run={run} />
          <h2 style={{ marginTop: ".6rem" }}>Whose problem is each gap?</h2>
          <GapCards scores={run.attribute_scores} />
          <Competitors run={run} />
          <Evidence run={run} />
        </div>
      )}

      {tab === "history" && <History runs={runs} onOpen={openRun} />}

      {tab === "compare" && (
        <div className="stack">
          <div className="card row" style={{ gap: "1rem", flexWrap: "wrap" }}>
            <label className="muted">Run A</label>
            <select value={cmpA} onChange={(e) => setCmpA(e.target.value)}>
              <option value="">choose…</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {runNames[r.id]?.full ?? r.id} · {r.alignment}%
                </option>
              ))}
            </select>
            <label className="muted">Run B</label>
            <select value={cmpB} onChange={(e) => setCmpB(e.target.value)}>
              <option value="">choose…</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {runNames[r.id]?.full ?? r.id} · {r.alignment}%
                </option>
              ))}
            </select>
          </div>
          {pairA && pairB ? <Compare a={pairA} b={pairB} runs={runs} />
            : <div className="card muted">Pick two runs to compare. Run both scenarios first if the list is short.</div>}
        </div>
      )}
    </div>
  );
}
