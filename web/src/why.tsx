import { useEffect, useRef, useState } from "react";
import type { Answer, Investigation, ReadStep, Run, WhyArm, WhyVerdict } from "./api";
import { getHealth, getInvestigations, streamWhy } from "./api";
import { latestPerClaim } from "./investigations";
import type { TermKey } from "./glossary";
import { PROVENANCE_LABEL } from "./labels";
import { Term } from "./popover";

const host = (u?: string | null) => (u ?? "").replace(/^https?:\/\/(www\.)?/, "").split("/")[0];

/** The page's words, without the stamps and headers the search tool put in front of them. */
const pageText = (t: string) => t
  .replace(/^(?:(?:Published|Crawled|Content type|Source): [^;\n]*;\s*)+/, "")
  .replace(/^Total lines: \d+\s*/, "")
  .replace(/^L\d+: /gm, "")
  .trim();

const STEP: Record<ReadStep["kind"], string> = { search: "Searched", open_page: "Opened", find_in_page: "Looked up" };

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * What the answering model read before it answered, in order: each search and the snippets it
 * returned, each page it opened and the lines it looked up in one. Recorded from the live call itself
 * (providers/live.reading_of), so it is the model's own reading list, not a reconstruction.
 */
export function WhatItRead({ a }: { a?: Answer }) {
  const steps = a?.trace;
  if (!steps?.length) return null;
  const searches = steps.filter((s) => s.kind === "search").length;
  const opened = steps.filter((s) => s.kind === "open_page").length;
  const results = steps.reduce((n, s) => n + s.results.length, 0);
  return (
    <details className="read">
      <summary>
        What AI read · {plural(searches, "search", "searches")}, {plural(results, "result")}
        {opened > 0 && `, ${plural(opened, "page")} opened`}
      </summary>
      <p className="muted">
        <Term k="what_ai_read" icon /> Everything the model was handed before it wrote this answer, as the
        search tool returned it. Page text is shortened here.
      </p>
      <ol className="read-steps">
        {steps.map((s, i) => (
          <li key={i}>
            <span className="read-kind">{STEP[s.kind]}</span>{" "}
            {s.kind === "search" ? s.queries.map((q) => `“${q}”`).join(", ")
              : <>{host(s.url)}{s.pattern && <> for “{s.pattern}”</>}</>}
            {s.results.length > 0 && (
              <ul className="read-results">
                {s.results.map((r, j) => (
                  <li key={j}>
                    <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title || host(r.url)}</a>
                    <span className="muted"> · {host(r.url)}{r.crawled && ` · crawled ${r.crawled}`}</span>
                    <span className="read-text">{pageText(r.text)}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
}

// ---------------------------------------------------------------- the why agent (why.py)

const VERDICT: Record<WhyVerdict["kind"], { label: string; tone: string }> = {
  caused_by: { label: "Cause found", tone: "contested" },
  over_determined: { label: "Several pages", tone: "contested" },
  prior_belief: { label: "Prior belief", tone: "unprioritised" },
  not_in_reading: { label: "Not from a page", tone: "neutral" },
  not_said: { label: "Not said", tone: "neutral" },
  copy_fix: { label: "Fix: copy", tone: "landed" },
  authority_fix: { label: "Fix: authority", tone: "imposed" },
  not_movable: { label: "Not movable by copy", tone: "neutral" },
  copy_lowers: { label: "Copy lowers it", tone: "contested" },
  not_reproducible: { label: "Not reproducible", tone: "neutral" },
  undecided: { label: "Undecided", tone: "neutral" },
  budget: { label: "Stopped at budget", tone: "neutral" },
};

const VERDICT_TERM: Partial<Record<WhyVerdict["kind"], TermKey>> = {
  copy_fix: "copy_fix", authority_fix: "authority_fix", not_movable: "not_movable",
  prior_belief: "prior_belief", over_determined: "over_determined",
};

const share = (k: number, n: number) => (n ? `${Math.round((100 * k) / n)}%` : "n/a");
const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(Math.round(x * 100))}`;

/** One experiment's effect as a dot and its interval on a −100…+100 axis. */
function EffectBar({ a }: { a: WhyArm }) {
  if (a.effect == null || !a.interval) return <span className="muted">—</span>;
  const x = (v: number) => 50 + 50 * v;
  const decided = a.decided === "effect";
  return (
    <svg className="effect-bar" viewBox="0 0 100 14" role="img"
         aria-label={`${signed(a.effect)} points, from ${signed(a.interval[0])} to ${signed(a.interval[1])}`}>
      <line x1="50" x2="50" y1="1" y2="13" className="effect-zero" />
      <line x1={x(a.interval[0])} x2={x(a.interval[1])} y1="7" y2="7" className="effect-ci" />
      <circle cx={x(a.effect)} cy="7" r="3.2" className={decided ? "effect-dot decided" : "effect-dot"} />
    </svg>
  );
}

/** The claim card the why agent produces: what AI says, why, whether it believes it, what fixes it. */
export function InvestigationCard({ inv }: { inv: Investigation }) {
  const base = inv.arms.find((a) => a.kind === "base");
  const fix = inv.verdicts.find((v) => v.fix);
  const cause = inv.verdicts.find((v) => !v.fix);
  const armOf = (v?: WhyVerdict) => inv.arms.find((a) => a.id === v?.arm_id);
  const lines = armOf(cause)?.kind === "drop_passage" ? armOf(cause)!.text : [];
  const shown = fix ?? cause;
  return (
    <article className="why-card">
      <header className="why-card-head">
        <strong>{inv.claim}</strong>
        {shown && <span className={`pill ${VERDICT[shown.kind].tone}`}>{VERDICT[shown.kind].label}</span>}
      </header>
      <p className="muted why-q">Asked: “{inv.question}”</p>
      <dl className="why-rows">
        <dt>AI says it</dt>
        <dd>
          In {inv.live.k} of {inv.live.n} live answers
          {base && base.n > 0 && <> · {base.k} of {base.n} (<b>{share(base.k, base.n)}</b>) when its reading list is{" "}
            <Term k="replay_experiment">replayed</Term></>}
        </dd>
        {inv.off.n > 0 && (
          <>
            <dt>Belief</dt>
            <dd>
              With web search off: {inv.off.k} of {inv.off.n}.{" "}
              {inv.off.k ? "The model already believes it." : "Not something it says from memory: it comes from search."}
            </dd>
          </>
        )}
        {cause && (
          <>
            <dt>Because of</dt>
            <dd>
              {VERDICT_TERM[cause.kind] ? <Term k={VERDICT_TERM[cause.kind]!}>{VERDICT[cause.kind].label}</Term>
                : VERDICT[cause.kind].label}: {cause.text}
              {lines.length > 0 && (
                <ul className="why-lines">{lines.map((l, i) => <li key={i}>{pageText(l)}</li>)}</ul>
              )}
            </dd>
          </>
        )}
        {fix && (
          <>
            <dt>Tested fix</dt>
            <dd>
              {VERDICT_TERM[fix.kind] ? <Term k={VERDICT_TERM[fix.kind]!}>{VERDICT[fix.kind].label}</Term> : VERDICT[fix.kind].label}
              : {fix.text}
              {armOf(fix)?.hypothetical && <> <span className="tag sample">hypothetical copy</span></>}
            </dd>
            <dt>Status</dt>
            <dd>
              {fix.fix === "none" ? "Nothing to publish for this question."
                : <><span className="pill unstated_intent">predicted</span> → published → re-crawled → checked live</>}
            </dd>
          </>
        )}
      </dl>
      {inv.arms.length > 0 && <details className="why-arms">
        <summary>{plural(inv.arms.length - 1, "experiment")} · <Term k="effect_interval">effect</Term> with its 95% interval</summary>
        <div className="tablewrap">
          <table>
            <thead><tr><th>What changed</th><th>Says it</th><th>Effect</th><th className="effect-col">−100 · 0 · +100</th></tr></thead>
            <tbody>
              {inv.arms.map((a) => (
                <tr key={a.id}>
                  <td>{a.label}{a.hypothetical && <> <span className="tag sample">hypothetical</span></>}</td>
                  <td>{a.k}/{a.n}{a.base_n > 0 && <span className="muted"> vs {a.base_k}/{a.base_n}</span>}</td>
                  <td>{a.decided === "base" ? "base" : a.effect == null ? "—"
                    : `${signed(a.effect)} pts${a.decided === "undecided" ? " (undecided)" : a.decided === "no_effect" ? " (none)" : ""}`}</td>
                  <td className="effect-col"><EffectBar a={a} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>}
      <p className="muted why-foot">
        {PROVENANCE_LABEL.counterfactual_replay}: it never moves a score. {inv.model}, judged by {inv.judge} ·
        spent ${inv.spent_usd.toFixed(2)} of ${inv.budget_usd.toFixed(2)}
        {inv.status === "stopped" && " · stopped at its budget"}
      </p>
    </article>
  );
}

/**
 * Ask why: pick a claim and a branded question and the why agent runs its experiments, streaming
 * what it does; past investigations of the run are listed below it. Live runs only.
 */
export function WhyPanel({ run }: { run: Run }) {
  const [past, setPast] = useState<Investigation[]>([]);
  const [budget, setBudget] = useState<number | null>(null);
  const named = run.probes.filter((p) => p.kind === "named" && p.phase === "baseline");
  const claims = [...(run.attributes ?? [])].sort((a, b) => Number(!!a.discovered) - Number(!!b.discovered));
  const [attribute, setAttribute] = useState(claims[0]?.id ?? "");
  const [probe, setProbe] = useState(named[0]?.id ?? OWN);
  const [question, setQuestion] = useState("");
  const [term, setTerm] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stop = useRef<(() => void) | null>(null);
  const live = run.mode === "live_api";

  useEffect(() => {
    if (!live) return;
    getInvestigations(run.id).then(setPast).catch(() => {});
    getHealth().then((h) => setBudget(h.why_budget_usd ?? null)).catch(() => {});
    return () => stop.current?.();
  }, [run.id, live]);

  if (!live) return null;
  const start = () => {
    setRunning(true); setError(null); setLog([]);
    stop.current = streamWhy(run.id, {
      attribute, term, ...(probe === OWN ? { question } : { probe }),
    }, {
      onStart: (e) => setBudget(e.budget_usd),
      onLog: (e) => setLog((l) => [...l, e.text]),
      onDone: (inv) => { setPast((p) => [inv, ...p]); setRunning(false); },
      onError: (e) => { setError(e.message); setRunning(false); },
    });
  };
  return (
    <section className="panel-sec why-panel">
      <div className="panel-sec-head">
        <h3><Term k="why_investigation">Why AI says it</Term></h3>
        <span className="block-found">{past.length ? `${plural(latestPerClaim(past).length, "claim")} investigated on this run` : "experiments on what AI read"}</span>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Pick a claim and a branded question. We ask it live and record <Term k="what_ai_read">what AI read</Term>, ask
        it with web search off, then change one thing at a time in what it read and ask again until the change is
        clear: which page makes AI say it, and whether your copy or your authority would change it.
        {budget != null && ` Each investigation spends at most $${budget.toFixed(2)}.`}
      </p>
      <form className="why-form" onSubmit={(e) => { e.preventDefault(); start(); }}>
        <label>Claim
          <select value={attribute} onChange={(e) => setAttribute(e.target.value)} disabled={running}>
            {claims.map((a) => <option key={a.id} value={a.id}>{a.label}{a.discovered ? " (AI's own)" : ""}</option>)}
          </select>
        </label>
        <label>Branded question
          <select value={probe} onChange={(e) => setProbe(e.target.value)} disabled={running}>
            {named.map((p) => <option key={p.id} value={p.id}>{p.text}</option>)}
            <option value={OWN}>Your own question…</option>
          </select>
        </label>
        {probe === OWN && (
          <label>Your question (must name {run.profile.name}, not the claim)
            <input value={question} maxLength={200} onChange={(e) => setQuestion(e.target.value)} disabled={running}
                   placeholder={`What makes ${run.profile.name} different?`} />
          </label>
        )}
        <label>Word that counts as saying it <span className="muted">(optional; otherwise a separate model judges)</span>
          <input value={term} maxLength={40} onChange={(e) => setTerm(e.target.value)} disabled={running} placeholder="e.g. AI" />
        </label>
        <button className="primary" type="submit" disabled={running || !attribute || (probe === OWN && !question.trim())}>
          {running ? "Running…" : "Ask why"}
        </button>
      </form>
      {error && <div className="callout error">{error}</div>}
      {(running || log.length > 0) && !error && (
        <ol className="why-log" aria-live="polite">{log.map((l, i) => <li key={i}>{l}</li>)}</ol>
      )}
      {latestPerClaim(past).map(({ latest, earlier }) => (
        <div key={latest.id} className="why-group">
          <InvestigationCard inv={latest} />
          {earlier.length > 0 && (
            <details className="why-earlier">
              <summary>{plural(earlier.length, "earlier investigation")} of this claim and question</summary>
              {earlier.map((inv) => <InvestigationCard key={inv.id} inv={inv} />)}
            </details>
          )}
        </div>
      ))}
    </section>
  );
}

const OWN = "__own__";
