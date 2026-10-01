import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import type { RetrievalRow, Run } from "../api";
import { PROVENANCE_LABEL, tabBadge, when } from "../labels";
import { GLOSSARY } from "../glossary";
import { FleetPanel } from "../fleet";
import { modelsOf, TABS, tabKey, winBackPlan } from "./util";
import type { ReportTab } from "./util";
import { Logo, Section } from "./ui";
import { Figures, PinnedLine, Explain } from "./figures";
import { BuyerQuestions, BrandQuestions } from "./questions";
import { PrintSummary } from "./print";
import { ZoneChips, Excluded, Weights, UpsideTable, Discovered } from "./claimCards";
import { Competitors, ShareOfVoice, CitationNetwork } from "./sources";
import { PositioningMapView } from "./map";
import { WhyTab, FixLine } from "./fixes";
import { WinBack } from "./winback";
import { HowWeChecked } from "./checks";

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
  const { answered, judged } = modelsOf(run);
  return (
    <p className="source">
      <strong>{PROVENANCE_LABEL.live_api}</strong> — answered by {answered || "the configured model"} via
      the OpenAI Responses API with web search{judged && (judged === answered ? `, judged by the same model` : `, judged by a separate model (${judged})`)}. This
      measures that API at this moment, not the ChatGPT consumer app. Answers with no search behind
      them are excluded from scores.
    </p>
  );
}

/** A tab label's native tooltip, for the tab named after the terms this product invented. */
const TAB_HINT: Partial<Record<ReportTab, string>> = {
  questions: `${GLOSSARY.buyer_question.term}: ${GLOSSARY.buyer_question.def} ${GLOSSARY.brand_question.term}: ${GLOSSARY.brand_question.def}`,
};
/** "#report-questions" opens the questions tab, so a link can land on one; the two tabs it replaced
 * ("#report-buyer", "#report-brand") land there too. */
const tabFromHash = (): ReportTab => {
  const hash = window.location.hash.replace(/^#report-(buyer|brand)$/, "#report-questions");
  return TABS.find(([t]) => hash === `#report-${t}`)?.[0] ?? "overview";
};

/**
 * One run as a product: a summary pinned at the top, then one tab per question a reader asks —
 * each fitting about one screen — with every claim and question readable in place. Same numbers
 * and data as ever; only the layout. `onRescored` enables the optional weights step; without it the
 * report is read-only.
 */
export function Report({ run, onRescored }: {
  run: Run;
  onRescored?: (r: Run) => void;
}) {
  const d = run.drift;
  const uid = useId();
  const top = useRef<HTMLDivElement>(null);
  const [tab, setTabState] = useState<ReportTab>(tabFromHash);
  const [reasks, setReasks] = useState<Record<string, RetrievalRow["reask"]>>({});
  const reasked = (probe: string, got: RetrievalRow["reask"]) => setReasks((m) => ({ ...m, [`${run.id}:${probe}`]: got }));
  useEffect(() => {
    const follow = () => setTabState(tabFromHash());
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  useEffect(() => {
    // On a phone the tab strip scrolls sideways: keep the chosen tab in view, including one opened by a link.
    const btn = document.getElementById(`${uid}-tab-${tab}`), strip = btn?.parentElement;
    if (btn && strip) strip.scrollLeft = btn.offsetLeft - strip.offsetLeft - 16;
  }, [tab, uid]);
  const [nudge, setNudge] = useState(true);
  // The header scrolls with the page; once it is out of view a one-line summary pins above the tabs.
  const head = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(false);
  useEffect(() => {
    const el = head.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => setPinned(!e.isIntersecting && e.boundingClientRect.top < 0));
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const setTab = (t: ReportTab, focus = false) => {
    setNudge(false);
    setTabState(t);
    window.history.replaceState(null, "", `#report-${t}`);
    if (focus) document.getElementById(`${uid}-tab-${t}`)?.focus();
    // A pinned header means the reader scrolled into the previous tab; start the new one at its top.
    const head = top.current;
    if (head && head.getBoundingClientRect().top <= 0) head.parentElement?.scrollIntoView({ block: "start" });
  };
  const onKey = (e: KeyboardEvent) => {
    const to = tabKey(e, TABS.findIndex(([t]) => t === tab), TABS.length);
    if (to != null) setTab(TABS[to][0], true);
  };

  const claims = run.attribute_scores.filter((s) => !s.discovered);
  // Badges say what they count, in words, and never a bare 0 that reads as a grade: a tab with
  // nothing to fix shows a tick, and one with nothing to list shows no badge.
  const badge: Record<ReportTab, string | undefined> = {
    overview: tabBadge(claims.length, "claim"),
    questions: tabBadge(run.probes.filter((p) => p.phase === "baseline").length, "question"),
    "win-back": tabBadge(winBackPlan(run).targets.length, "claim", "✓"),
    why: tabBadge(run.audit?.claims.filter((c) => c.checks.some((k) => k.status === "fail")).length, "claim", "✓"),
    sources: tabBadge(run.insights?.sources.sources.length, "site"),
  };

  return (
    <article className="report">
      <div className="report-head" ref={head}>
        <div className="row" style={{ minWidth: 0 }}>
          <Logo name={run.profile.name} url={run.profile.logo_url} size={34} />
          <div style={{ minWidth: 0 }}>
            <h2>{run.profile.name}</h2>
            <div className="muted" title={run.id}>
              {when(run.created_at)} · {run.mode === "live_api" ? PROVENANCE_LABEL.live_api : "Sample run — authored answers"}
              {run.mode === "live_api" && modelsOf(run).answered && ` · answered by ${modelsOf(run).answered}`}
              {run.mode === "live_api" && modelsOf(run).judged && `, judged by ${modelsOf(run).judged}`}
            </div>
          </div>
        </div>
        {d && <PrintSummary run={run} />}
        {d && <Figures d={d} brand={run.profile.name} run={run} onQuickWins={() => setTab("win-back")} />}
      </div>
      <div className={`report-top${pinned ? " pinned" : ""}`} ref={top}>
        {d && pinned && <PinnedLine d={d} run={run} />}
        {d && (
          <div className={`report-tabs${nudge ? " nudge" : ""}`} role="tablist" aria-label="Report sections" onKeyDown={onKey}>
            {TABS.map(([t, label], i) => (
              <button key={t} id={`${uid}-tab-${t}`} role="tab" className="rtab" aria-selected={tab === t}
                      style={{ "--i": i } as CSSProperties}
                      aria-controls={`${uid}-panel-${t}`} tabIndex={tab === t ? 0 : -1} onClick={() => setTab(t)}
                      title={TAB_HINT[t]}>
                {label}
                {badge[t] && <span className="rtab-count">{badge[t]}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      {d ? (
        <div className="report-panel" role="tabpanel" id={`${uid}-panel-${tab}`} aria-labelledby={`${uid}-tab-${tab}`}
             tabIndex={0}>
          {tab === "overview" && (
            <>
              <RunSource run={run} />
              <Explain d={d} brand={run.profile.name} />
              <FixLine run={run} onOpen={() => setTab("why")} />
              <ZoneChips run={run} />
              <Excluded run={run} />
              {onRescored && <Weights key={run.id} run={run} onRescored={onRescored} />}
              <HowWeChecked run={run} />
            </>
          )}
          {tab === "win-back" && (
            <>
              <FleetPanel run={run} />
              <WinBack run={run} />
              <Section title="Where the upside is" found="the biggest open claims first">
                <UpsideTable run={run} />
              </Section>
            </>
          )}
          {tab === "questions" && <div className="qboard"><BuyerQuestions run={run} /><BrandQuestions run={run} /></div>}
          {tab === "why" && <WhyTab run={run} reasks={reasks} onReasked={reasked} />}
          {tab === "sources" && (
            <>
              <CitationNetwork run={run} />
              <ShareOfVoice run={run} />
              <PositioningMapView run={run} />
              <Competitors run={run} />
              <Discovered run={run} />
            </>
          )}
        </div>
      ) : (
        <>
          <RunSource run={run} />
          <div className="callout">This run finished without a report.</div>
        </>
      )}
    </article>
  );
}
