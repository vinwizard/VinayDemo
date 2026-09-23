import { useCallback, useEffect, useState } from "react";
import type { CompanyDetail, Health, PassStatus, Run, RunSummary } from "./api";
import { API, exchangePass, getCompany, getHealth, getPass, getRun, getRuns } from "./api";
import { Compare, History, Logo, Report } from "./components";
import { day, headline, potentialText, runLabels } from "./labels";
import { CompanyWorkflow } from "./workflow";

type Tab = "preloaded" | "showcase" | "onboard" | "history" | "compare";

// A personal link (?pass=…) is read once and leaves the address bar before anything renders, so the
// code is not left in history or passed on by copying the URL. The effect below trades it for an
// HttpOnly session cookie.
const PASS_CODE = (() => {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("pass");
  if (code) {
    url.searchParams.delete("pass");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
  return code;
})();

/** A mailto link to ask for live access, subject prefilled. */
function Contact({ email }: { email?: string }) {
  if (!email) return <>the demo's owner</>;
  const subject = encodeURIComponent("Positioning Drift - live access request");
  return <a href={`mailto:${email}?subject=${subject}`}>{email}</a>;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("preloaded");
  const [health, setHealth] = useState<Health | null>(null);
  const [seed, setSeed] = useState<CompanyDetail["profile"] | null>(null);
  const [showcase, setShowcase] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pass, setPass] = useState<PassStatus | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [opened, setOpened] = useState<Run | null>(null);
  const [cmpA, setCmpA] = useState(""), [cmpB, setCmpB] = useState("");
  const [pairA, setPairA] = useState<Run | null>(null), [pairB, setPairB] = useState<Run | null>(null);

  const refreshRuns = useCallback(() => {
    getRuns().then(setRuns).catch(() => {});
    getPass().then((p) => setPass(p.pass)).catch(() => {});
  }, []);

  useEffect(() => {
    // Everything else waits for the session: runs and companies are listed per pass.
    const signIn = PASS_CODE
      ? exchangePass(PASS_CODE).then((r) => r.pass).catch((e: Error) => { setError(e.message); return null; })
      : getPass(true).then((r) => r.pass).catch(() => null);
    signIn.then((p) => {
      setPass(p);
      refreshRuns();
      return getHealth();
    }).then((h) => {
      setHealth(h);
      getCompany(h.seed_company).then((c) => setSeed(c.profile)).catch(() => {});
      getRun(h.showcase.run).then(setShowcase).catch(() => {});
    })
      .catch(() => setError(`Could not reach the API at ${API}. Start it first — see WEB.md.`));
  }, [refreshRuns]);

  const openRun = (id: string) => { getRun(id).then(setOpened).catch((e) => setError(String(e))); };

  // The meter moves while a run is spending, so it is re-read while a pass is open.
  useEffect(() => {
    if (!pass) return;
    const t = window.setInterval(() => getPass().then((p) => setPass(p.pass)).catch(() => {}), 10000);
    return () => window.clearInterval(t);
  }, [pass]);

  useEffect(() => {
    if (cmpA) getRun(cmpA).then(setPairA).catch(() => setPairA(null));
    if (cmpB) getRun(cmpB).then(setPairB).catch(() => setPairB(null));
  }, [cmpA, cmpB]);

  const runNames = runLabels(runs);
  const tabs: [Tab, string][] = [
    ["preloaded", seed?.name ?? "Notion"], ["showcase", showcase?.profile.name ?? "Profound"],
    ["onboard", "Onboard your own company"], ["history", "History"], ["compare", "Compare"],
  ].filter(([t]) => !(health?.public_demo && !pass && t === "onboard") && (t !== "showcase" || showcase)) as [Tab, string][];

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
              {t === "showcase" && showcase && <Logo name={showcase.profile.name} url={showcase.profile.logo_url} size={18} />}
              {label}
            </button>
          ))}
        </nav>
      </header>

      {pass && (
        <div className={`callout meter${pass.capped ? " warn-box" : ""}`} role="status">
          <div className="row" style={{ justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
            <span>Live pass for <strong>{pass.label}</strong></span>
            <strong>${pass.spent_usd.toFixed(2)} of ${pass.cap_usd.toFixed(2)} used</strong>
          </div>
          <div className="meter-track" aria-hidden="true">
            <div style={{ width: `${Math.min(100, (100 * pass.spent_usd) / (pass.cap_usd || 1))}%` }} />
          </div>
          <span className="muted">
            {pass.capped
              ? <>This pass has reached its limit. The saved reports stay open; email <Contact email={health?.contact_email} /> for a higher limit.</>
              : <>Onboard a company and measure it live on real models. Your runs are visible only to you.
                  This pass includes ${pass.cap_usd.toFixed(2)} of live runs; need more? Email <Contact email={health?.contact_email} /> to have it raised.</>}
          </span>
        </div>
      )}
      {health?.public_demo && !pass && (
        <div className="callout warn-box">
          <strong>Public demo — saved runs only.</strong> Apart from the {showcase?.profile.name ?? "Profound"} report,
          a real live run saved earlier, every answer here is a bundled sample, and no AI model is called.
          Want to try it live on your own company? Email <Contact email={health.contact_email} /> from your work email
          and you will get a personal link.
        </div>
      )}
      {error && <div className="callout error">{error}</div>}

      {/* Both company tabs stay mounted, so a measurement keeps streaming while you look elsewhere. */}
      <div hidden={tab !== "preloaded"}>
        {health && <CompanyWorkflow companyId={health.seed_company} preloaded publicDemo={health.public_demo}
                                     onRunSaved={refreshRuns} />}
      </div>
      {tab === "showcase" && showcase && (
        <div className="stack">
          <p className="muted" style={{ margin: 0 }}>
            A real live run, saved on {day(showcase.created_at)}: {showcase.profile.domain} was read and
            its claims put to AI as unbranded and branded questions. Opening this tab replays nothing and asks no model.
            The intent weights are an example set for this demo, not {showcase.profile.name}’s own.
          </p>
          <Report run={showcase} onRescored={setShowcase} />
        </div>
      )}
      <div hidden={tab !== "onboard"}>
        {health && !health.live_available && (
          <div className="callout warn-box">
            No API key is configured on the server, so reading a site and measuring it will fail.
            Put <code>OPENAI_API_KEY</code> in <code>.env</code> and restart the API.
          </div>
        )}
        {health && <CompanyWorkflow onRunSaved={refreshRuns} />}
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
