import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Investigation, Run, Verification, WhyVerdict, WinBackAction } from "../api";
import { getHealth, getInvestigations, streamRecheck, streamRewriteTest } from "../api";
import { MATCH_STEP, matchRows, matchVerdict, wordDiff, wordsIn } from "../quickwins";
import type { MatchVerdict } from "../quickwins";
import { ZONE_LABEL, plural } from "../labels";
import { Popover, Term } from "../popover";
import { refs, winBackPlan } from "./util";
import { Section } from "./ui";
import { QRef } from "./questions";
import { ClaimDetail } from "./claimCards";

/** What a rewrite changes on its page: a word diff when it replaces copy, else the new passage. The
 * heading is the buyer question the passage answers. */
function WhatChanges({ a }: { a: WinBackAction }) {
  const parts = a.current_copy ? wordDiff(a.current_copy, a.rewrite) : null;
  return (
    <div className="changes">
      <h4>What changes on <a href={a.page_url} target="_blank" rel="noreferrer">{shortPage(a.page_url)}</a></h4>
      {a.heading && <p className="diff-heading"><ins>{a.heading}</ins></p>}
      {parts ? (
        <p className="diff">
          {parts.map((d, i) => d.op === "same" ? <span key={i}>{d.text} </span>
            : d.op === "add" ? <ins key={i}>{d.text}</ins> : <del key={i}>{d.text}</del>).reduce<ReactNode[]>(
            (out, el, i) => (i ? [...out, " ", el] : [el]), [])}
        </p>
      ) : <p className="diff"><ins>{a.rewrite}</ins></p>}
      <p className="muted">
        {parts ? `${plural(wordsIn(parts, "add"), "word")} added, ${wordsIn(parts, "del")} removed`
          : "A new passage: nothing on the page is replaced"}
        {a.heading ? ", headed by the buyer's own question." : "."}
      </p>
    </div>
  );
}

const shortPage = (u: string) => u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");

/** Step ① as a table: per targeted question, today's best passage, the page AI cited, and with the
 * rewrite, from the retrieval simulation (the same scores as Why AI misses you → Test a fix). */
function MatchTable({ a, run }: { a: WinBackAction; run: Run }) {
  const rows = matchRows(a, run.retrieval?.rows ?? []);
  const cited = new Map((run.retrieval?.rows ?? []).map((r) => [r.probe_id, r.rival?.url]));
  if (!run.retrieval) return <p className="muted">No match scores for this run.</p>;
  return (
    <div className="table-scroll">
      <table className="compact">
        <thead><tr><th>Buyer question</th><th className="num">Today</th><th className="num">Page AI cited</th>
          <th className="num">With the rewrite</th><th>Change</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.probe_id}>
              <td><QRef id={r.probe_id} run={run} text /></td>
              <td className="num">{r.today?.toFixed(2) ?? "–"}</td>
              <td className="num">{r.cited != null
                ? <span title={cited.get(r.probe_id) ?? undefined}>{r.cited.toFixed(2)}</span> : "–"}</td>
              <td className="num">{r.fixed?.toFixed(2) ?? "–"}</td>
              <td>{r.change == null ? <span className="muted">not scored</span>
                : r.change >= MATCH_STEP ? <span className="ok">closer ({signed(r.change)})</span>
                : r.change <= -MATCH_STEP ? <span className="worse">worse ({signed(r.change)})</span>
                : <span className="muted">no change ({signed(r.change)})</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(2)}`;

const REPLAY_LABEL: Partial<Record<WhyVerdict["kind"], { label: string; tone: string }>> = {
  copy_fix: { label: "Proven", tone: "good" }, authority_fix: { label: "Proven once found", tone: "good" },
  not_movable: { label: "No change", tone: "caution" }, copy_lowers: { label: "Makes it worse", tone: "caution" },
  not_reproducible: { label: "Could not be tested", tone: "plain" }, undecided: { label: "Not decided", tone: "plain" },
  budget: { label: "Stopped at budget", tone: "plain" }, cancelled: { label: "Stopped", tone: "plain" },
  ceiling: { label: "Already at the top", tone: "plain" },
};

/** Step ② for one buyer question: its latest replay test, or the button that runs one. */
function ReplayTest({ run, a, probe, inv, budget, onDone }: {
  run: Run; a: WinBackAction; probe: string; inv?: Investigation; budget: number | null; onDone: (i: Investigation) => void;
}) {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);
  const verdict = inv?.verdicts.at(-1);
  const tag = verdict && REPLAY_LABEL[verdict.kind];
  const start = () => {
    setBusy(true); setError(null); setLog([]);
    stop.current = streamRewriteTest(run.id, a.attribute_id, probe, {
      onLog: (e) => setLog((l) => [...l, e.text]),
      onDone: (i) => { setBusy(false); onDone(i); },
      onError: (e) => { setBusy(false); setError(e.message); },
    });
  };
  return (
    <div className="replay">
      <QRef id={probe} run={run} text />
      {verdict ? (
        <p>{tag && <span className={`pill ${tag.tone}`}>{tag.label}</span>} {verdict.text}{" "}
          <span className="muted">({inv!.spent_usd.toFixed(2)} USD, replays with search off; {inv!.judge})</span></p>
      ) : run.mode === "live_api" ? (
        <button type="button" className="ghost" disabled={busy} onClick={start}>
          {busy ? "Testing…" : `Run replay test${budget != null ? ` (up to $${budget.toFixed(2)})` : ""}`}
        </button>
      ) : <p className="muted">A sample run cannot be tested: its answers were written by hand.</p>}
      {busy && log.length > 0 && <ol className="why-log" aria-live="polite">{log.map((l, i) => <li key={i}>{l}</li>)}</ol>}
      {error && <div className="callout error">{error}</div>}
    </div>
  );
}

/** Step ③: "Mark fix live" on a proven rewrite, once it is published. */
function LiveCheck({ inv, onChecked }: { inv?: Investigation; onChecked?: (v: Verification) => void }) {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const proven = inv && inv.verdicts.some((v) => v.fix === "copy" || v.fix === "authority");
  if (!inv || !proven) return <p className="muted">Once a replay test proves the rewrite, publish it, then check it here.</p>;
  const v = inv.verification;
  const run = () => {
    setBusy(true); setError(null); setLog([]);
    streamRecheck(inv.id, {
      onLog: (e) => setLog((l) => [...l, e.text]),
      onDone: (x) => { setBusy(false); onChecked?.(x); },
      onError: (e) => { setBusy(false); setError(e.message); },
    });
  };
  return (
    <div className="replay">
      {v && <p><strong>{v.verdict.replace(/_/g, " ")}:</strong> {v.text}</p>}
      <button type="button" className="ghost" disabled={busy} onClick={run}>
        {busy ? "Checking…" : v ? "Check again" : "Mark fix live"}
      </button>
      <span className="muted"> The page is read first, free; only a published fix is asked about live.</span>
      {busy && log.length > 0 && <ol className="why-log" aria-live="polite">{log.map((l, i) => <li key={i}>{l}</li>)}</ol>}
      {error && <div className="callout error">{error}</div>}
    </div>
  );
}

/** One rewrite's verdict line, from the strongest evidence there is: live, replay, then the match check. */
function rewriteVerdict(match: MatchVerdict, tests: Investigation[]): { text: string; tone: string } {
  const kinds = tests.map((t) => t.verdicts.at(-1)?.kind);
  const does = (t: Investigation) => (t.counts === "recommends" ? "recommends" : "names");
  const confirmed = tests.find((t) => t.verification?.verdict === "confirmed");
  if (confirmed) return { text: `Confirmed live: AI now ${does(confirmed)} you for it.`, tone: "good" };
  if (kinds.some((k) => k === "copy_fix" || k === "authority_fix")) return { text: "Proven in replay: publish it, then mark it live.", tone: "good" };
  const lowers = tests.find((t) => t.verdicts.at(-1)?.kind === "copy_lowers");
  if (lowers) return { text: `Disproven: in replay it makes AI ${does(lowers) === "recommends" ? "recommend" : "name"} you less. Don't publish it.`, tone: "caution" };
  const moved = kinds.filter((k) => k !== "ceiling");
  if (moved.length && moved.every((k) => k === "not_movable")) return { text: "Disproven: in replay it changes nothing. Don't publish it as is.", tone: "caution" };
  if (tests.length && !moved.length) return { text: `Already at the top: in replay AI already ${does(tests[0])} you for ${tests.length === 1 ? "this question" : "these questions"}, so no rewrite can show a gain.`, tone: "plain" };
  if (match === "worse") return { text: "Don't publish: it matches the buyer questions worse than today's copy.", tone: "caution" };
  return { text: "Not proven yet: run a replay test before publishing.", tone: "plain" };
}

/** One rewrite as a ranked row: a one-line summary, then what changes, why, and its proof. */
function RewriteRow({ a, rank, run, invs, budget, onInv }: {
  a: WinBackAction; rank: number | null; run: Run; invs: Investigation[]; budget: number | null;
  onInv: (i: Investigation) => void;
}) {
  const rows = matchRows(a, run.retrieval?.rows ?? []);
  const m = matchVerdict(rows);
  const tests = a.question_ids.map((q) => latestTest(invs, a.attribute_id, q)).filter(Boolean) as Investigation[];
  const verdict = rewriteVerdict(m.verdict, tests);
  const score = run.attribute_scores.find((s) => s.attribute_id === a.attribute_id);
  const one = rows.length === 1 && rows[0].change != null;
  return (
    <li>
      <details open={rank === 1}>
        <summary>
          <span className="rank">{rank ?? "–"}</span>
          <span className="r-title">{a.label}</span>
          <span className="chev" aria-hidden="true">▸</span>
          <span className="r-meta">
            <span className={`pill ${m.verdict === "worse" ? "caution" : m.verdict === "closer" ? "good" : "plain"}`}>
              {one ? `Match ${rows[0].today?.toFixed(2)} → ${rows[0].fixed?.toFixed(2)}`
                : m.verdict === "not_scored" ? "Match not scored"
                : `Match: closer on ${m.closer} of ${m.scored}, worse on ${m.worse}`}
            </span>
            <span className={`pill ${tests.length ? verdict.tone : "plain"}`}>{tests.length ? `Replay: ${tests.length} of ${a.question_ids.length} tested` : "Replay: not tested"}</span>
            <span>{plural(a.question_ids.length, "buyer question")}</span>
          </span>
        </summary>
        <div className="x-body">
          <WhatChanges a={a} />
          <div>
            <h4>Why this rewrite</h4>
            <p>{a.why || "No reason was given."}</p>
          </div>
          <div className="proof">
            <h4>Proof</h4>
            <ol className="ladder">
              <li className={m.verdict === "worse" ? "bad-step" : ""}>
                <strong>① <Term k="retrieval_score">Match check</Term></strong> <span className="muted">free, already done</span>
                <MatchTable a={a} run={run} />
              </li>
              <li>
                <strong>② <Term k="replay_test">Replay test</Term></strong> <span className="muted">before you publish</span>
                {a.question_ids.map((q) => (
                  <ReplayTest key={q} run={run} a={a} probe={q} inv={latestTest(invs, a.attribute_id, q)} budget={budget}
                              onDone={onInv} />
                ))}
              </li>
              <li>
                <strong>③ <Term k="fix_recheck">Live check</Term></strong> <span className="muted">after you publish</span>
                {tests.filter((t) => t.verdicts.some((v) => v.fix === "copy" || v.fix === "authority")).map((t) => (
                  <LiveCheck key={t.id} inv={t} onChecked={(v) => onInv({ ...t, verification: v })} />
                ))}
                {!tests.some((t) => t.verdicts.some((v) => v.fix === "copy" || v.fix === "authority")) && <LiveCheck />}
              </li>
            </ol>
          </div>
          <p className={`verdict-line ${verdict.tone}`}><strong>Verdict:</strong> {verdict.text}</p>
          {score && <div><Popover wide label={a.label} className="linky" trigger="All evidence"><ClaimDetail s={score} run={run} /></Popover></div>}
        </div>
      </details>
    </li>
  );
}

const latestTest = (invs: Investigation[], attribute: string, probe: string) =>
  invs.filter((i) => i.kind === "buyer" && i.attribute_id === attribute && i.probe_id === probe)
    .sort((x, y) => y.created_at.localeCompare(x.created_at))[0];

/** A fix inside a claim's popover: the rewrite and where it goes, briefly. The proof lives on Quick wins. */
export function FixCard({ a, run }: { a: WinBackAction; run: Run }) {
  const zone = run.attribute_scores.find((s) => s.attribute_id === a.attribute_id)?.zone ?? a.zone;
  return (
    <div className="question">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <strong>{a.label}</strong>
        <span className={`pill ${zone}`}>{ZONE_LABEL[zone]}</span>
      </div>
      {run.mode !== "live_api" && <span className="tag sample">sample</span>}
      <WhatChanges a={a} />
      {a.question_ids.length ? <p className="muted" style={{ margin: 0 }}>For {refs(a.question_ids, run)}.</p>
        : <span className="muted">No unbranded question in this run asks for this — add one to the next run to measure it.</span>}
      {a.why && <span className="muted">{a.why}</span>}
      <a href="#report-win-back">Its proof is on Quick wins</a>
    </div>
  );
}

export function WinBack({ run }: { run: Run }) {
  const { targets, actions } = winBackPlan(run);
  const [invs, setInvs] = useState<Investigation[]>([]);
  const [budget, setBudget] = useState<number | null>(null);
  const live = run.mode === "live_api";
  useEffect(() => {
    if (!live) return;
    getInvestigations(run.id).then(setInvs).catch(() => {});
    getHealth().then((h) => setBudget(h.why_budget_usd ?? null)).catch(() => {});
  }, [run.id, live]);
  if (!targets.length) return null;
  const onInv = (i: Investigation) => setInvs((xs) => [i, ...xs.filter((x) => x.id !== i.id)]);
  const planned = new Set(actions.map((a) => a.attribute_id));
  const unplanned = targets.filter((s) => !planned.has(s.attribute_id));
  const questions = new Set(actions.flatMap((a) => a.question_ids)).size;
  const verdicts = new Map(actions.map((a) => [a.attribute_id, matchVerdict(matchRows(a, run.retrieval?.rows ?? [])).verdict]));
  const stand = actions.filter((a) => verdicts.get(a.attribute_id) !== "worse");
  const fall = actions.filter((a) => verdicts.get(a.attribute_id) === "worse");
  const proven = actions.filter((a) => invs.some((i) => i.kind === "buyer" && i.attribute_id === a.attribute_id
    && i.verdicts.some((v) => v.fix === "copy" || v.fix === "authority"))).length;
  return (
    <Section title={<Term k="quick_wins">Quick wins</Term>}
           found={`${plural(targets.length, "claim")} with room to grow · `
             + (actions.length ? `${proven} of ${plural(actions.length, "rewrite")} proven`
                 + (questions ? ` · ${plural(questions, "unbranded question")} to win` : "")
               : "no suggested fix passed our checks yet")}>
      <p style={{ margin: 0 }}>
        For each claim with room to grow: a new passage for one of your pages, headed by a buyer's own question,
        why it should make AI name {run.profile.name}, and its proof. A draft — check every statement against the
        product before publishing. It changes no number in this report.
      </p>
      {actions.length > 0 && (
        <>
          <p className="ladder-legend muted">
            <span>① <Term k="retrieval_score">Match check</Term>: free, already done</span>
            <span>② <Term k="replay_test">Replay test</Term>: before you publish{budget != null ? `, up to $${budget.toFixed(2)} a question` : ""}</span>
            <span>③ <Term k="fix_recheck">Live check</Term>: after you publish</span>
          </p>
          <ul className="ranked">
            {stand.map((a, i) => <RewriteRow key={a.attribute_id} a={a} rank={i + 1} run={run} invs={invs} budget={budget} onInv={onInv} />)}
            {fall.length > 0 && (
              <li className="sep">Rewrites we could not stand behind ({fall.length}): our own match check says they match the buyer questions worse than today's copy</li>
            )}
            {fall.map((a) => <RewriteRow key={a.attribute_id} a={a} rank={null} run={run} invs={invs} budget={budget} onInv={onInv} />)}
          </ul>
        </>
      )}
      {unplanned.length > 0 && (
        <p className="muted" style={{ margin: 0 }}>
          No suggested fix passed our checks yet for {unplanned.map((s) => s.label).join(", ")}
          {(run.win_back_notes ?? []).length > 0 ? ": the reasons are below, or it became a claim with room to grow when the run was re-scored." : "."}
        </p>
      )}
      {(run.win_back_notes ?? []).length > 0 && (
        <details className="block">
          <summary><span className="block-title">Suggestions we could not confirm</span>
            <span className="block-found">{plural(run.win_back_notes!.length, "reason")}</span></summary>
          <div className="block-body">
            <p className="muted" style={{ margin: 0 }}>
              A suggestion is shown only if the page it names is one we read, it is headed by a buyer's question,
              it says why it should work, it does not mostly repeat the copy it replaces, and it states facts, not marketing words.
            </p>
            <ul>{run.win_back_notes!.map((n, i) => <li key={i}>{n}</li>)}</ul>
          </div>
        </details>
      )}
    </Section>
  );
}
