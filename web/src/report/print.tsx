import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { AttributeScore, Run } from "../api";
import { GAP_ZONES, ZONE_ORDER } from "../api";
import { PROVENANCE_LABEL, ZONE_LABEL, ZONE_MEANING, headline, when } from "../labels";
import { GLOSSARY } from "../glossary";
import { aiShare, printedRange, FRONT_TERM, frontsOf, gapSentence, modelsOf } from "./util";
import { Logo } from "./ui";
import { Visibility } from "./figures";

/** Top 3 landed claims, most-endorsed first: what AI already says for you. */
const topWins = (scores: AttributeScore[]) => scores
  .filter((s) => s.zone === "landed")
  .sort((a, b) => (b.echo_rate ?? 0) - (a.echo_rate ?? 0))
  .slice(0, 3);

/** Top 3 open claims, in the same order as "Where the upside is". */
const topFixes = (scores: AttributeScore[]) => scores
  .filter((s) => GAP_ZONES.includes(s.zone))
  .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
  .slice(0, 3);

/**
 * "Download summary (PDF)": mounts a one-page summary on <body> and opens the browser's print
 * dialog, where "Save as PDF" makes the file. Print CSS shows only the summary; on screen it never
 * renders, so there is no second copy of the report to keep in sync.
 */
export function PrintSummary({ run }: { run: Run }) {
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    if (!printing) return;
    const done = () => setPrinting(false);
    window.addEventListener("afterprint", done);
    window.print();
    return () => window.removeEventListener("afterprint", done);
  }, [printing]);
  return (
    <>
      <button className="ghost" onClick={() => setPrinting(true)}>Download summary (PDF)</button>
      {printing && createPortal(<ExecSummary run={run} />, document.body)}
    </>
  );
}

/** The one-page summary itself: logo, the potential with the real score beneath, 3 wins, 3 fixes. */
function ExecSummary({ run }: { run: Run }) {
  const d = run.drift!;
  const h = headline(d);
  const wins = topWins(run.attribute_scores);
  const fixes = topFixes(run.attribute_scores);
  const live = run.mode === "live_api";
  return (
    <section className="exec-summary">
      <div className="row">
        <Logo name={run.profile.name} url={run.profile.logo_url} size={48} />
        <div>
          <h2>{run.profile.name}</h2>
          <div className="muted">How AI answer engines describe {run.profile.name} — executive summary</div>
        </div>
      </div>
      <div className="figure potential">
        <div className="label">{h.label}</div>
        <div className="value">
          {h.potential == null ? "n/a" : `${h.potential}%`}
          {h.potential != null && <small> untapped potential</small>}
        </div>
        <div className="today">{h.today ?? d.na_reasons?.[h.field]}</div>
      </div>
      {frontsOf(d).length ? (
        <p className="exec-vis">
          {frontsOf(d).map((v) => (
            <span key={v.front}>
              <strong>{v.front === "both" ? "Where AI places you = where you aim to be"
                : GLOSSARY[FRONT_TERM[v.front as "placed" | "aiming"]].term} ({v.category}):</strong>{" "}
              <Visibility d={v} />{v.visibility != null && printedRange(v, v.interval)}
              {v.low_confidence && <><br /><span className="muted">{v.low_confidence}</span></>}
              <br />
            </span>
          ))}
          {gapSentence(d, run.profile.name)}
        </p>
      ) : (
        <p className="exec-vis">
          <strong>Buyer visibility:</strong> <Visibility d={d} />
          {d.visibility == null ? ` — ${d.na_reasons?.visibility ?? "not measured"}`
            : printedRange(d, d.visibility_interval)}
          {d.low_confidence && <><br /><span className="muted">{d.low_confidence}</span></>}
        </p>
      )}
      <div className="exec-cols">
        <div>
          <h3>Top wins — AI already says it</h3>
          {wins.length ? (
            <ol>{wins.map((s) => (
              <li key={s.attribute_id}><strong>{s.label}</strong><div className="muted">{aiShare(s)}</div></li>
            ))}</ol>
          ) : <p className="muted">No claim has landed yet.</p>}
        </div>
        <div>
          <h3>Top fixes — where the upside is</h3>
          {fixes.length ? (
            <ol>{fixes.map((s) => (
              <li key={s.attribute_id}>
                <strong>{s.label}</strong> <span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span>
                <div className="muted">{ZONE_MEANING[s.zone]}</div>
              </li>
            ))}</ol>
          ) : <p className="muted">No open opportunity: every claim has landed or is unweighted.</p>}
        </div>
      </div>
      <p className="exec-foot">
        Source: <strong>{live ? PROVENANCE_LABEL.live_api : "SYNTHETIC SAMPLE — authored answers, not measured"}</strong>
        {live && modelsOf(run).answered && ` · answered by ${modelsOf(run).answered}`}
        {" "}· run {when(run.created_at)} · {d.n_named} brand and {d.n_blind} buyer answers
        · printed {new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
        <br />Independent portfolio demo.
      </p>
    </section>
  );
}
