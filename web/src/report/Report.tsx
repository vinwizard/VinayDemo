import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import type { RetrievalRow, Run } from "../api";
import { PROVENANCE_LABEL, headline, when } from "../labels";
import { useReportTour } from "../guideBus";
import { investigateExample, measuredWhat } from "../tour";
import { Popover } from "../popover";
import { FleetPanel } from "../fleet";
import { PastInvestigations } from "../why";
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

/** The Evidence page's parts, in reading order: id (`#evidence-<id>`) and the tab's words. */
const PARTS = [
  ["questions", "What we asked AI"], ["searches", "What AI searched"], ["fixes", "Fixes and tests"],
  ["site", "Site check"], ["sources", "Cited sites and rivals"], ["checks", "How we checked"],
  ["investigate", "Investigate the gaps"],
] as const;
type PartId = (typeof PARTS)[number][0];

/** What Investigate the gaps does, above its button, told with this run's own Quick win. */
function InvestigateIntro({ run }: { run: Run }) {
  return (
    <div className="callout investigate-intro">
      <strong>Why does AI say what it says about {run.profile.name}, and what would change it?</strong>
      <p>
        The results show what AI says. Investigating works out why. A coordinator picks the claims AI misses
        and a branded question for each. Investigators record what AI read for that question, then hand AI
        the same reading with one thing changed (a page removed, a few lines removed, a rewrite put in) and
        ask again, many times. A critic challenges the verdicts that did not decide, and the fixes that
        worked come back as a ranked, tested plan.
      </p>
      <p>{investigateExample(run)}</p>
      <p className="muted">It needs a live model and a pass; the button shows what it will cost before you start.</p>
    </div>
  );
}

/**
 * One run as two pages. Results: the headline and five more result blocks, each figure animating in
 * once, everything else one hover or tap away. Evidence: one part at a time on its own tab: every
 * question and answer, the searches, the fixes and their tests, the site check, the cited sites, how
 * we checked, and on a live run Investigate the gaps. The page and the tab are kept in the URL hash
 * (`#evidence`, `#evidence-<part>`), so Back returns to the tab or the results before.
 */
export function Report({ run }: { run: Run }) {
  const d = run.drift;
  const top = useRef<HTMLElement>(null);
  const tabsAt = useRef<HTMLDivElement>(null);
  const figure = d ? headline(d) : null;
  useReportTour({ brand: run.profile.name, today: figure?.value, potential: figure?.potential,
                  what: measuredWhat(run.profile.name, d?.lens), live: run.mode === "live_api" ? 1 : null,
                  example: investigateExample(run) }, top);
  const [hash, setHash] = useState(() => window.location.hash);
  const [reasks, setReasks] = useState<Record<string, RetrievalRow["reask"]>>({});
  const reasked = (probe: string, got: RetrievalRow["reask"]) => setReasks((m) => ({ ...m, [`${run.id}:${probe}`]: got }));
  useEffect(() => {
    // A report on a tab out of view (the onboarding one behind History) keeps its page.
    const follow = () => { if (top.current?.getClientRects().length) setHash(window.location.hash); };
    window.addEventListener("hashchange", follow);
    window.addEventListener("popstate", follow);
    return () => { window.removeEventListener("hashchange", follow); window.removeEventListener("popstate", follow); };
  }, []);
  const evidence = hash.startsWith("#evidence");
  // A page switch starts at its top; a tab switch stays put, unless the page was scrolled past the
  // tabs, which then come back to the top of the screen. Opening the report does not move it.
  const shown = useRef(window.location.hash);
  useEffect(() => {
    const was = shown.current;
    shown.current = hash;
    if (was === hash) return;
    if (was.startsWith("#evidence") !== evidence) top.current?.scrollIntoView({ block: "start" });
    else if ((tabsAt.current?.getBoundingClientRect().top ?? 0) < 0) tabsAt.current?.scrollIntoView({ block: "start" });
  }, [hash, evidence]);
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
          <button type="button" className="primary" data-tour="evidence" onClick={() => go("evidence")}>Evidence →</button>
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
  const parts = PARTS.filter(([p]) => (p === "searches" ? !!run.insights?.searches : p === "fixes" ? fixes
    : p === "investigate" ? run.mode === "live_api" : true));
  const asked = hash.slice("#evidence-".length);
  const part: PartId = parts.find(([p]) => p === asked)?.[0] ?? parts[0][0];
  const tabId = (p: PartId) => `${run.id}-tab-${p}`;
  // Arrow keys, Home and End move between the tabs, as in any tab list.
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const at = parts.findIndex(([p]) => p === part);
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: parts.length - 1 }[e.key];
    if (to == null) return;
    e.preventDefault();
    const [p] = parts[(to + parts.length) % parts.length];
    go(`evidence-${p}`);
    requestAnimationFrame(() => document.getElementById(tabId(p))?.focus());
  };
  const panel = (p: PartId, body: ReactNode, className = "ev-part") => (
    <div id={`evidence-${p}`} className={className} role="tabpanel" aria-labelledby={tabId(p)} hidden={part !== p}>{body}</div>
  );
  return (
    <article className="report" ref={top}>
      <div className="report-head">
        <button type="button" className="linky back" onClick={() => go("")}>← Results</button>
        {head(`${run.profile.name} · Evidence`)}
        <div className="row" data-tour="ev-downloads">
          <PrintSummary run={run} />
          <button type="button" className="ghost" onClick={() => downloadRun(run)}>Data (JSON)</button>
        </div>
      </div>
      <SampleBanner run={run} />
      <div ref={tabsAt} />
      <div className="ev-tabs" role="tablist" aria-label="Evidence" data-tour="ev-tabs" onKeyDown={onKey}>
        {parts.map(([p, label]) => (
          <button key={p} id={tabId(p)} type="button" role="tab" aria-selected={part === p} aria-controls={`evidence-${p}`}
                  tabIndex={part === p ? 0 : -1} className={p === "investigate" ? "ev-tab investigate" : "ev-tab"}
                  data-tour={p === "investigate" ? "ev-tab-investigate" : undefined} onClick={() => go(`evidence-${p}`)}>
            {label}
          </button>
        ))}
      </div>
      {panel("questions", <><BuyerQuestions run={run} /><BrandQuestions run={run} /></>, "ev-part qboard")}
      {run.insights?.searches && panel("searches", <WhatItSearched run={run} />)}
      {fixes && panel("fixes", <><WinBack run={run} /><TestAFix run={run} reasks={reasks} onReasked={reasked} /></>)}
      {panel("site", <WhyAIMisses run={run} />)}
      {panel("sources", <><CitationNetwork run={run} /><Competitors run={run} /></>)}
      {panel("checks", <><Excluded run={run} /><HowWeChecked run={run} /></>)}
      {run.mode === "live_api" && panel("investigate", <><InvestigateIntro run={run} /><FleetPanel run={run} /><PastInvestigations run={run} /></>)}
    </article>
  );
}
