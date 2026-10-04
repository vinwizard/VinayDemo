import { useEffect, useRef, useState } from "react";
import type { RetrievalRow, Run } from "../api";
import { PROVENANCE_LABEL, when } from "../labels";
import { Popover } from "../popover";
import { FleetPanel } from "../fleet";
import { WhyAIMisses } from "../audit";
import { modelsOf, winBackPlan } from "./util";
import { Logo } from "./ui";
import { Headline, BuyerVisibility } from "./figures";
import { BuyerQuestions, BrandQuestions } from "./questions";
import { PrintSummary } from "./print";
import { ZoneChips, Excluded } from "./claimCards";
import { Competitors, ShareOfVoice, CitationNetwork } from "./sources";
import { WhyNumbers, WhatItSearched, TestAFix } from "./fixes";
import { QuickWins, WinBack } from "./winback";
import { HowWeChecked } from "./checks";

/**
 * Where these answers came from, always in view: a pill on both pages, and on a replayed run the
 * loudest banner on the page. Presenting authored answers as measured is the one failure this
 * product cannot have, so neither is ever behind a hover; only who answered and judged is.
 */
function Provenance({ run }: { run: Run }) {
  if (run.mode !== "live_api") return <span className="pill sample-pill">SYNTHETIC — authored answers, not asked</span>;
  const { answered, judged } = modelsOf(run);
  return (
    <Popover label={PROVENANCE_LABEL.live_api} className="pill live" trigger={<>● {PROVENANCE_LABEL.live_api} · {when(run.created_at)}</>}>
      <strong className="pop-title">{PROVENANCE_LABEL.live_api}</strong>
      <p>
        Answered by {answered || "the configured model"} via the OpenAI Responses API with web search
        {judged && (judged === answered ? ", judged by the same model" : `, judged by a separate model (${judged})`)}.
        This measures that API at this moment, not the ChatGPT consumer app. Answers with no search behind
        them are excluded from scores.
      </p>
    </Popover>
  );
}

function SampleBanner({ run }: { run: Run }) {
  if (run.mode === "live_api") return null;
  return (
    <div className="callout sample">
      <strong>SYNTHETIC DEMO — fixture replay; no live chatbot measurements; model judgment simulated.</strong>
      {" "}Every answer in this run was authored, not asked.
    </div>
  );
}

/** The whole run as JSON, workflow log included: the page shows the checks, the file keeps every step. */
function downloadRun(run: Run) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${run.profile.name.replace(/\W+/g, "-")}-${run.id}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The Evidence page's parts, in reading order: id (`#evidence-<id>`) and the link's words. */
const PARTS = [
  ["questions", "Questions"], ["searches", "What AI searched"], ["fixes", "Fixes and tests"],
  ["site", "Site check"], ["sources", "Cited sites and rivals"], ["checks", "How we checked"],
] as const;

/**
 * One run as two pages. Results: the headline and five more result blocks, each figure animating in
 * once, everything else one hover or tap away. Evidence: every question and answer, the searches,
 * the fixes and their tests, the site check, the cited sites and how we checked. The page is kept
 * in the URL hash (`#evidence`, `#evidence-<part>`), so Back returns to the results.
 */
export function Report({ run }: { run: Run }) {
  const d = run.drift;
  const top = useRef<HTMLElement>(null);
  const [hash, setHash] = useState(() => window.location.hash);
  const [reasks, setReasks] = useState<Record<string, RetrievalRow["reask"]>>({});
  const reasked = (probe: string, got: RetrievalRow["reask"]) => setReasks((m) => ({ ...m, [`${run.id}:${probe}`]: got }));
  useEffect(() => {
    const follow = () => setHash(window.location.hash);
    window.addEventListener("hashchange", follow);
    window.addEventListener("popstate", follow);
    return () => { window.removeEventListener("hashchange", follow); window.removeEventListener("popstate", follow); };
  }, []);
  const evidence = hash.startsWith("#evidence");
  // A page switch starts at its top, or at the part a link named; opening the report does not move it
  // unless its link named a part.
  const shown = useRef(window.location.hash.startsWith("#evidence-") ? null : window.location.hash);
  useEffect(() => {
    if (shown.current === hash) return;
    shown.current = hash;
    const part = hash.length > 1 ? document.getElementById(hash.slice(1)) : null;
    (part ?? top.current)?.scrollIntoView({ block: "start" });
  }, [hash]);
  const go = (to: string) => {
    window.history.pushState(null, "", to ? `#${to}` : window.location.pathname + window.location.search);
    setHash(to ? `#${to}` : "");
  };

  const head = (title: string) => (
    <div className="row head-brand">
      <Logo name={run.profile.name} url={run.profile.logo_url} size={34} />
      <h2 title={run.id}>{title}</h2>
      <Provenance run={run} />
    </div>
  );

  if (!d) {
    return (
      <article className="report" ref={top}>
        <div className="report-head">{head(run.profile.name)}</div>
        <SampleBanner run={run} />
        <div className="callout">This run finished without a report.</div>
      </article>
    );
  }

  if (!evidence) {
    return (
      <article className="report" ref={top}>
        <div className="report-head">
          {head(run.profile.name)}
          <button type="button" className="primary" onClick={() => go("evidence")}>Evidence →</button>
        </div>
        <SampleBanner run={run} />
        <div className="tiles">
          <Headline run={run} />
          <BuyerVisibility run={run} />
          <ZoneChips run={run} />
          <QuickWins run={run} onOpen={() => go("evidence-fixes")} />
          <WhyNumbers run={run} onOpen={(to) => go(`evidence-${to}`)} />
          <ShareOfVoice run={run} />
        </div>
        <button type="button" className="ev-link" onClick={() => go("evidence")}>
          <span><strong>Evidence</strong> <span className="muted">· every question and answer · the searches · fixes and
            tests · site check · cited sites · how we checked · PDF and JSON</span></span>
          <span aria-hidden="true">→</span>
        </button>
      </article>
    );
  }

  const fixes = winBackPlan(run).targets.length > 0 || !!run.retrieval || run.mode === "live_api";
  const parts = PARTS.filter(([p]) => (p === "searches" ? !!run.insights?.searches : p === "fixes" ? fixes : true));
  return (
    <article className="report" ref={top}>
      <div className="report-head">
        <button type="button" className="linky back" onClick={() => go("")}>← Results</button>
        {head(`${run.profile.name} · Evidence`)}
        <div className="row">
          <PrintSummary run={run} />
          <button type="button" className="ghost" onClick={() => downloadRun(run)}>Data (JSON)</button>
        </div>
      </div>
      <SampleBanner run={run} />
      <nav className="ev-nav" aria-label="Evidence">
        {parts.map(([p, label]) => <a key={p} href={`#evidence-${p}`}>{label}</a>)}
      </nav>
      <div id="evidence-questions" className="ev-part qboard"><BuyerQuestions run={run} /><BrandQuestions run={run} /></div>
      {run.insights?.searches && <div id="evidence-searches" className="ev-part"><WhatItSearched run={run} /></div>}
      {fixes && (
        <div id="evidence-fixes" className="ev-part">
          <WinBack run={run} />
          <TestAFix run={run} reasks={reasks} onReasked={reasked} />
          <FleetPanel run={run} />
        </div>
      )}
      <div id="evidence-site" className="ev-part"><WhyAIMisses run={run} /></div>
      <div id="evidence-sources" className="ev-part"><CitationNetwork run={run} /><Competitors run={run} /></div>
      <div id="evidence-checks" className="ev-part"><Excluded run={run} /><HowWeChecked run={run} /></div>
    </article>
  );
}
