import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Investigation, Run, Verification, WhyVerdict, WinBackAction } from "../api";
import { getHealth, getInvestigations, streamRecheck, streamRewriteTest } from "../api";
import { MATCH_STEP, matchRows, matchVerdict, wordDiff, wordsIn } from "../quickwins";
import type { MatchVerdict } from "../quickwins";
import { ZONE_LABEL, address, plural } from "../labels";
import { Popover, Term } from "../popover";
import { refs, winBackPlan } from "./util";
import { Block, Section, Tile } from "./ui";
import { QRef } from "./questions";
import { ClaimDetail } from "./claimCards";

/** A rewrite as a word diff when it replaces copy, else the new passage. */
function Diff({ a }: { a: WinBackAction }) {
  const parts = a.current_copy ? wordDiff(a.current_copy, a.rewrite) : null;
  if (!parts) return <ins>{a.rewrite}</ins>;
  return <>{parts.map((d, i) => d.op === "same" ? <span key={i}>{d.text} </span>
    : d.op === "add" ? <ins key={i}>{d.text}</ins> : <del key={i}>{d.text}</del>).reduce<ReactNode[]>(
    (out, el, i) => (i ? [...out, " ", el] : [el]), [])}</>;
}

/** What a rewrite changes on its page. The heading is the buyer question the passage answers. */
function WhatChanges({ a }: { a: WinBackAction }) {
  const parts = a.current_copy ? wordDiff(a.current_copy, a.rewrite) : null;
  return (
    <div className="changes">
      <h4>What changes on <a href={a.page_url} target="_blank" rel="noreferrer">{address(a.page_url)}</a></h4>
      {a.heading && <p className="diff-heading"><ins>{a.heading}</ins></p>}
      <p className="diff"><Diff a={a} /></p>
      <p className="muted">
        {parts ? `${plural(wordsIn(parts, "add"), "word")} added, ${wordsIn(parts, "del")} removed`
          : "A new passage: nothing on the page is replaced"}
        {a.heading ? ", headed by the buyer's own question." : "."}
      </p>
    </div>
  );
}

/** A replay test that proved the rewrite moves AI. */
const isProven = (i: Investigation) => i.verdicts.some((v) => v.fix === "copy" || v.fix === "authority");

/** The match check as a table: per targeted question, today's best passage, the page AI cited, and
 * with the rewrite, from the retrieval simulation (the same scores as Test a fix). */
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

/** The replay test for one buyer question: its latest result, or the button that runs one. */
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

/** "Mark fix live" on a proven rewrite, once it is published. */
function LiveCheck({ inv, onChecked }: { inv: Investigation; onChecked: (v: Verification) => void }) {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const v = inv.verification;
  const run = () => {
    setBusy(true); setError(null); setLog([]);
    streamRecheck(inv.id, {
      onLog: (e) => setLog((l) => [...l, e.text]),
      onDone: (x) => { setBusy(false); onChecked(x); },
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
function rewriteVerdict(match: MatchVerdict, tests: Investigation[]): { label: string; text: string; tone: string } {
  const kinds = tests.map((t) => t.verdicts.at(-1)?.kind);
  const does = (t: Investigation) => (t.counts === "recommends" ? "recommends" : "names");
  const confirmed = tests.find((t) => t.verification?.verdict === "confirmed");
  if (confirmed) return { label: "Confirmed live", text: `Confirmed live: AI now ${does(confirmed)} you for it.`, tone: "good" };
  if (kinds.some((k) => k === "copy_fix" || k === "authority_fix")) return { label: "Proven in replay", text: "Proven in replay: publish it, then mark it live.", tone: "good" };
  const lowers = tests.find((t) => t.verdicts.at(-1)?.kind === "copy_lowers");
  if (lowers) return { label: "Disproven", text: `Disproven: in replay it makes AI ${does(lowers) === "recommends" ? "recommend" : "name"} you less. Don't publish it.`, tone: "caution" };
  const moved = kinds.filter((k) => k !== "ceiling");
  if (moved.length && moved.every((k) => k === "not_movable")) return { label: "Disproven", text: "Disproven: in replay it changes nothing. Don't publish it as is.", tone: "caution" };
  if (tests.length && !moved.length) return { label: "Already at the top", text: `Already at the top: in replay AI already ${does(tests[0])} you for ${tests.length === 1 ? "this question" : "these questions"}, so no rewrite can show a gain.`, tone: "plain" };
  if (match === "worse") return { label: "Don't publish", text: "Don't publish: it matches the buyer questions worse than today's copy.", tone: "caution" };
  return { label: "Not proven yet", text: "Not proven yet: run a replay test before publishing.", tone: "plain" };
}

/** One rewrite as a ranked row: a one-line verdict, then what changes, the one next step, and its
 * proof behind a disclosure. */
function RewriteRow({ a, rank, run, invs, budget, onInv }: {
  a: WinBackAction; rank: number | null; run: Run; invs: Investigation[]; budget: number | null;
  onInv: (i: Investigation) => void;
}) {
  const m = matchVerdict(matchRows(a, run.retrieval?.rows ?? []));
  const tests = a.question_ids.map((q) => latestTest(invs, a.attribute_id, q)).filter(Boolean) as Investigation[];
  const verdict = rewriteVerdict(m.verdict, tests);
  const proven = tests.filter(isProven);
  const next = a.question_ids.find((q) => !latestTest(invs, a.attribute_id, q));
  const score = run.attribute_scores.find((s) => s.attribute_id === a.attribute_id);
  return (
    <li>
      <details open={rank === 1}>
        <summary>
          <span className="rank">{rank ?? "–"}</span>
          <span className="r-title">{a.label}</span>
          <span className="chev" aria-hidden="true">▸</span>
          <span className="r-meta">
            <span className={`pill ${verdict.tone}`}>{verdict.label}</span>
            <span>{plural(a.question_ids.length, "buyer question")}</span>
          </span>
        </summary>
        <div className="x-body">
          <WhatChanges a={a} />
          <p className={`verdict-line ${verdict.tone}`}><strong>Verdict:</strong> {verdict.text}</p>
          {proven.length ? proven.map((t) => <LiveCheck key={t.id} inv={t} onChecked={(v) => onInv({ ...t, verification: v })} />)
            : next && <ReplayTest run={run} a={a} probe={next} budget={budget} onDone={onInv} />}
          <details className="proof">
            <summary>Proof details</summary>
            <h4>Why this rewrite</h4>
            <p>{a.why || "No reason was given."}</p>
            <h4><Term k="retrieval_score">Match check</Term> · free, already done</h4>
            <MatchTable a={a} run={run} />
            <h4><Term k="replay_test">Replay tests</Term> · before you publish</h4>
            {tests.length ? tests.map((t) => <ReplayTest key={t.id} run={run} a={a} probe={t.probe_id!} inv={t} budget={budget} onDone={onInv} />)
              : <p className="muted">None run yet.</p>}
            {score && <p><Popover wide label={a.label} className="linky" trigger="All evidence for this claim"><ClaimDetail s={score} run={run} /></Popover></p>}
          </details>
        </div>
      </details>
    </li>
  );
}

const latestTest = (invs: Investigation[], attribute: string, probe: string) =>
  invs.filter((i) => i.kind === "buyer" && i.attribute_id === attribute && i.probe_id === probe)
    .sort((x, y) => y.created_at.localeCompare(x.created_at))[0];

/** A fix inside a claim's popover: the rewrite and where it goes, briefly. The proof is on Evidence. */
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
      <a href="#evidence-fixes">Its proof is on the Evidence page</a>
    </div>
  );
}

export function WinBack({ run }: { run: Run }) {
  const { targets, actions } = winBackPlan(run);
  const [invs, setInvs] = useState<Investigation[]>([]);
  const [budget, setBudget] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const live = run.mode === "live_api";
  useEffect(() => {
    if (!live) return;
    getInvestigations(run.id).then(setInvs)
      .catch((e: Error) => setLoadError(`Could not load the investigations already run: ${e.message}`));
    // without a health reading the budget line is left out; the server still enforces the budget
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
  const proven = actions.filter((a) => invs.some((i) => i.kind === "buyer" && i.attribute_id === a.attribute_id && isProven(i))).length;
  return (
    <Section title={<Term k="quick_wins">Quick wins</Term>}
           found={`${plural(targets.length, "claim")} with room to grow · `
             + (actions.length ? `${proven} of ${plural(actions.length, "rewrite")} proven`
                 + (questions ? ` · ${plural(questions, "unbranded question")} to win` : "")
               : "no suggested fix passed our checks yet")}>
      <p className="muted" style={{ margin: 0 }}>
        A draft per claim with room to grow: check every statement against the product before publishing. It
        changes no number in this report.
      </p>
      {loadError && <div className="callout error">{loadError}</div>}
      {actions.length > 0 && (
        <>
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
        <Block title="Suggestions we could not confirm" found={plural(run.win_back_notes!.length, "reason")}>
          <p className="muted" style={{ margin: 0 }}>
            A suggestion is shown only if the page it names is one we read, it is headed by a buyer's question,
            it says why it should work, it does not mostly repeat the copy it replaces, and it states facts, not marketing words.
          </p>
          <ul>{run.win_back_notes!.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </Block>
      )}
    </Section>
  );
}

/** The Quick wins result block: how many rewrites, and the first one as a diff teaser. */
export function QuickWins({ run, onOpen }: { run: Run; onOpen: () => void }) {
  const { targets, actions } = winBackPlan(run);
  const first = actions.find((a) => matchVerdict(matchRows(a, run.retrieval?.rows ?? [])).verdict !== "worse") ?? actions[0];
  return (
    <Tile tour="quick-wins" title={<Term k="quick_wins">Quick wins</Term>} sample={run.mode !== "live_api" && !!first}>
      <span className="tile-big">{actions.length ? plural(actions.length, "rewrite") : "None yet"}</span>
      {first ? <p className="diff teaser"><span className="muted">{address(first.page_url)}: </span><Diff a={first} /></p>
        : <p className="muted">{targets.length ? "No suggested fix passed our checks yet." : "No claim with room to grow."}</p>}
      {actions.length > 0 && <button type="button" className="linky" onClick={onOpen}>See and test them →</button>}
    </Tile>
  );
}
