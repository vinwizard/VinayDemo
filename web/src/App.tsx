import { useCallback, useEffect, useMemo, useState } from "react";
import type { Health, PassStatus, Run, RunSummary } from "./api";
import { API, exchangePass, getHealth, getPass, getRun, getRuns } from "./api";
import { Report } from "./report/Report";
import { History } from "./report/history";
import { CompanyWorkflow } from "./workflow";
import { Guide } from "./guide";
import { headline, money, unreadableNote } from "./labels";
import { pickStory } from "./tour";

type Tab = "onboard" | "history";

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

/** Leaving a report drops its page from the address bar, so the next report opens on its results. */
const closeReport = () => window.history.replaceState(null, "", window.location.pathname + window.location.search);

/** A mailto link to ask for live access, subject prefilled. */
function Contact({ email }: { email?: string }) {
  if (!email) return <>the demo's owner</>;
  const subject = encodeURIComponent("Off Message - live access request");
  return <a href={`mailto:${email}?subject=${subject}`}>{email}</a>;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("onboard");
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pass, setPass] = useState<PassStatus | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runsNote, setRunsNote] = useState<string | null>(null);   // runs that could not be listed
  const [opened, setOpened] = useState<Run | null>(null);
  // The committed live run the "how it works" story is told with; a pass holder cannot read it.
  const [showcase, setShowcase] = useState<Run | null>(null);
  const [replay, setReplay] = useState(0);
  const story = useMemo(() => (showcase ? pickStory(showcase) : null), [showcase]);
  const storyVars = useMemo(() => {
    const h = showcase?.drift ? headline(showcase.drift) : null;
    return { today: h?.value, potential: h?.potential };
  }, [showcase]);

  const refreshRuns = useCallback(() => {
    getRuns().then((r) => { setRuns(r.items); setRunsNote(unreadableNote(r.unreadable, "run")); })
      .catch((e: Error) => setRunsNote(`Could not load the saved runs: ${e.message}`));
    // The meter keeps its last reading; it is read again every 10 seconds while a pass is open.
    getPass().then((p) => setPass(p.pass)).catch(() => {});
  }, []);

  useEffect(() => {
    // Everything else waits for the session: runs and companies are listed per pass.
    const signIn = PASS_CODE
      ? exchangePass(PASS_CODE).then((r) => r.pass).catch((e: Error) => { setError(e.message); return null; })
      // no session reads as no pass; an API that cannot be reached is reported by getHealth below
      : getPass(true).then((r) => r.pass).catch(() => null);
    signIn.then((p) => {
      setPass(p);
      refreshRuns();
      return getHealth().then((h) => ({ h, p }));
    }).then(({ h, p }) => {
      setHealth(h);
      // The public demo cannot onboard without a pass, so its visitors land on the saved runs.
      if (h.public_demo && !p) setTab("history");
      // A pass holder cannot read the showcase run, by design: the guide then shows the welcome alone.
      if (h.showcase?.run) getRun(h.showcase.run).then(setShowcase).catch(() => {});
    })
      .catch(() => setError(`Could not reach the API at ${API}. Start it first — see WEB.md.`));
  }, [refreshRuns]);

  const openRun = (id: string) => { getRun(id).then(setOpened).catch((e) => setError(String(e))); };

  // The meter moves while a run is spending, so it is re-read while a pass is open.
  useEffect(() => {
    if (!pass) return;
    // a missed reading keeps the last one until the next tick, 10 seconds on
    const t = window.setInterval(() => getPass().then((p) => setPass(p.pass)).catch(() => {}), 10000);
    return () => window.clearInterval(t);
  }, [pass]);

  const tabs: [Tab, string][] = [
    ["onboard", "Onboard your own company"], ["history", "History"],
  ].filter(([t]) => !(health?.public_demo && !pass && t === "onboard")) as [Tab, string][];

  return (
    <div className="shell">
      <header className="topbar">
        <h1>Off Message</h1>
        <div className="topbar-end">
          <nav className="tabs" role="tablist">
            {tabs.map(([t, label]) => (
              <button key={t} role="tab" className="tab" aria-selected={tab === t}
                      onClick={() => { setTab(t); if (t === "history") { closeReport(); setOpened(null); } }}>
                {label}
              </button>
            ))}
          </nav>
          {health && <button type="button" className="ghost how" onClick={() => setReplay((n) => n + 1)}>How it works</button>}
        </div>
      </header>

      {pass && (
        <div className={`callout meter${pass.capped ? " warn-box" : ""}`} role="status">
          <div className="row" style={{ justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
            <span>Live pass for <strong>{pass.label}</strong></span>
            <strong>{money(pass.spent_usd)} of {money(pass.cap_usd)} used</strong>
          </div>
          <div className="meter-track" aria-hidden="true">
            <div style={{ width: `${Math.min(100, (100 * pass.spent_usd) / (pass.cap_usd || 1))}%` }} />
          </div>
          <span className="muted">
            {pass.capped
              ? <>This pass has reached its limit. The saved reports stay open; email <Contact email={health?.contact_email} /> for a higher limit.</>
              : <>Onboard a company and measure it live on real models. Your runs are visible only to you.
                  This pass includes {money(pass.cap_usd)} of live runs; need more? Email <Contact email={health?.contact_email} /> to have it raised.</>}
          </span>
        </div>
      )}
      {health?.public_demo && !pass && (
        <div className="callout">
          <strong>Public demo — saved runs only.</strong> Apart from the run marked Measured live, every
          answer here is a bundled sample, and no AI model is called.
          Want to try it live on your own company? Email <Contact email={health.contact_email} /> from your work email
          and you will get a personal link.
        </div>
      )}
      {error && <div className="callout error">{error}</div>}

      <div hidden={tab !== "onboard"}>
        {health && <CompanyWorkflow onRunSaved={refreshRuns} warning={!health.key_configured ? (
          <div className="callout warn-box">
            No API key is configured on the server, so reading a site and measuring it will fail.
            {!health.public_demo && <> Put <code>OPENAI_API_KEY</code> in <code>.env</code> and restart the API.</>}
          </div>
        ) : !health.live_available && (
          <div className="callout warn-box">
            Live runs need your personal pass link. Open it in this browser to run live, or email{" "}
            <Contact email={health.contact_email} /> to get one.
          </div>
        )} />}
      </div>

      {tab === "history" && (opened ? (
        <div className="stack">
          <button className="linky back" onClick={() => { closeReport(); setOpened(null); }}>← All runs</button>
          <Report run={opened} />
        </div>
      ) : <>
        {runsNote && <div className="callout warn-box">{runsNote}</div>}
        <History runs={runs} onOpen={openRun} />
      </>)}

      <footer className="foot">Independent portfolio demo.</footer>
      <Guide story={story} vars={storyVars} replay={replay}
             auto={!!health && (!!pass || (!!story && !!health.public_demo && tab === "history" && !opened))}
             onOpenShowcase={() => {
               if (!showcase) return;
               closeReport();
               setTab("history"); setOpened(showcase);
             }} />
    </div>
  );
}
