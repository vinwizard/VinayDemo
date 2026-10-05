import { useCallback, useEffect, useRef, useState } from "react";
import type { Challenge, FleetEstimate, FleetSummary, PlanItem, Run, Verification, WhyVerdict } from "./api";
import { getFleets, getHealth, startFleet, streamFleet, streamVerify } from "./api";
import type { FleetView, Lane } from "./fleetlog";
import { emptyView, fold } from "./fleetlog";
import { PROVENANCE_LABEL, WHY_VERDICT, address, money, plural, signed, when } from "./labels";
import { Term } from "./popover";
import { READ_ONLY_NOTE } from "./report/ui";

const minutes = (s: number) => (s >= 90 ? `${(s / 60).toFixed(1)} min` : `${Math.round(s)} s`);

const CHALLENGE_LABEL: Record<Challenge["kind"], string> = {
  thin: "Thin", ceiling: "Ceiling", floor: "Not said here", not_reproducible: "Not reproducible",
  off_claim: "Quotes off the claim",
  contradicts: "Contradicts",
};
const ASK_LABEL: Record<Challenge["ask"], string> = {
  other_question: "asks for another question", more_budget: "asks for more budget", accept: "accepts it as it is",
};
const FIX: Record<PlanItem["fix"], { label: string; tone: string }> = {
  copy: { label: "Tested fix: copy", tone: "landed" },
  authority: { label: "Tested fix: authority", tone: "imposed" },
  source: { label: "Address the source", tone: "contested" },
  none: { label: "Not movable here", tone: "neutral" },
  thin: { label: "Not decided", tone: "neutral" },
  untested: { label: "Untested", tone: "unstated_intent" },
};
const CHECK: Record<Verification["verdict"], { label: string; tone: string }> = {
  not_published: { label: "Not published", tone: "neutral" },
  not_crawled: { label: "Not crawled yet", tone: "neutral" },
  confirmed: { label: "Confirmed", tone: "landed" },
  not_confirmed: { label: "Not confirmed", tone: "contested" },
  undecided: { label: "Not decided yet", tone: "neutral" },
  model_moved: { label: "Model changed", tone: "unprioritised" },
  budget: { label: "Stopped at budget", tone: "neutral" },
};
const STATUS: Record<Lane["status"], string> = {
  waiting: "waiting for a lane", running: "running", cancelling: "stopping at its deadline", finished: "finished",
  failed: "failed", skipped: "skipped",
};

/** Where a lane sits on the fleet's clock, as fractions of the whole so far. */
function span(l: Lane, t0: number, now: number) {
  const total = Math.max(1, now - t0);
  const a = l.began == null ? null : (l.began - t0) / total;
  const b = (l.ended ?? now) - t0;
  return a == null ? null : { left: Math.max(0, a), width: Math.max(0.01, b / total - a) };
}

function LaneRow({ l, t0, now }: { l: Lane; t0: number; now: number }) {
  const s = span(l, t0, now);
  const main = l.verdicts.find((v) => v.kind === "copy_fix" || v.kind === "authority_fix") ?? l.verdicts[l.verdicts.length - 1];
  return (
    <li className={`fleet-lane ${l.status}`} data-task={l.task.id}>
      <div className="fleet-lane-head">
        <strong>{l.task.claim}</strong>
        <span className="muted"> · “{l.task.question}”{l.task.term && <> · counts “{l.task.term}”</>}</span>
        {l.task.try_no > 1 && <span className="tag">try {l.task.try_no}</span>}
        {l.task.by === "code" && <span className="tag">picked by code</span>}
      </div>
      <div className="fleet-track" aria-hidden="true">
        {s && <span className={`fleet-bar ${l.status}`} style={{ left: `${100 * s.left}%`, width: `${100 * Math.min(s.width, 1 - s.left)}%` }} />}
      </div>
      <div className="fleet-lane-state">
        <span className="muted">{STATUS[l.status]}
          {l.began != null && ` · ${minutes(((l.ended ?? now) - l.began) / 1000)}`}
          {l.arms > 0 && ` · ${plural(l.arms, "experiment")}`}
          {l.spent != null && ` · ${money(l.spent)}`}</span>
        {main && <span className="pill neutral">{WHY_VERDICT[main.kind as WhyVerdict["kind"]]?.label ?? main.kind}</span>}
      </div>
      <p className="fleet-reason muted">{l.task.reason}</p>
      {l.status === "running" && l.last && <p className="fleet-last">{l.last}</p>}
      {l.error && <p className="fleet-last">{l.error}</p>}
      {main && l.status !== "running" && <p className="fleet-last">{main.text}</p>}
      {l.challenges.map((c, i) => (
        <p key={i} className="fleet-challenge">
          <Term k="fleet_critic">Critic</Term>: <b>{CHALLENGE_LABEL[c.kind]}</b> — {c.text}{" "}
          <span className="muted">It {ASK_LABEL[c.ask]}.</span>
        </p>
      ))}
      {l.decided && <p className="muted fleet-decided">→ {l.decided}</p>}
    </li>
  );
}

function Numbers({ i }: { i: PlanItem }) {
  if (!i.n) return null;
  return (
    <span className="muted">
      {i.k}/{i.n} against {i.base_k}/{i.base_n} in replays
      {i.effect != null && ` · ${signed(i.effect)} pts`}
      {i.interval && ` (${signed(i.interval[0])} to ${signed(i.interval[1])})`}
    </span>
  );
}

function PlanCard({ i, check, running, onCheck }: {
  i: PlanItem; check?: FleetView["checks"][number]; running: boolean; onCheck: () => void;
}) {
  const fix = FIX[i.fix];
  const v = check?.v;
  return (
    <li className="plan-item" data-rank={i.rank}>
      <div className="plan-head">
        <span className="plan-rank">{i.rank}</span>
        <strong>{i.claim}</strong>
        <span className={`pill ${fix.tone}`}>{fix.label}</span>
      </div>
      <p className="plan-text">{i.text}</p>
      {(i.page_url || i.n > 0) && (
        <p className="plan-meta">
          {i.page_url && <><a href={i.page_url} target="_blank" rel="noopener noreferrer">{address(i.page_url)}</a>{" · "}</>}
          <Numbers i={i} />
          {i.hypothetical && <> <span className="tag sample">hypothetical copy</span></>}
        </p>
      )}
      {i.rewrite && i.fix !== "untested" && <blockquote className="plan-rewrite">{i.rewrite}</blockquote>}
      {i.sources.length > 0 && (
        <ul className="plan-sources">{i.sources.map((u) => <li key={u}><a href={u} target="_blank" rel="noopener noreferrer">{address(u)}</a></li>)}</ul>
      )}
      {i.notes.map((n, k) => <p key={k} className="muted plan-note">⚠ {n}</p>)}
      {(i.fix === "copy" || i.fix === "authority") && (
        <div className="plan-check">
          <button type="button" className="ghost" disabled={running} onClick={onCheck}>
            {v ? "Re-check again" : "Mark fix live — re-check"}
          </button>
          <Term k="fix_recheck" icon />
          {check && !v && <span className="muted">{check.error ?? check.log[check.log.length - 1] ?? "Checking…"}</span>}
          {v && (
            <div className="plan-verdict">
              <span className={`pill ${CHECK[v.verdict].tone}`}>{CHECK[v.verdict].label}</span> {v.text}
              {v.live.n > 0 && (
                <p className="muted">
                  Measured live after the fix ({PROVENANCE_LABEL[v.live_provenance] ?? v.live_provenance}): said in{" "}
                  {v.live.k} of {v.live.n}, AI read the fix in {v.read_by_ai.k} of {v.read_by_ai.n}. Predicted in replay:{" "}
                  {v.predicted.k} of {v.predicted.n}. {v.control.n > 0 && `Old reading list today: ${v.control.k} of ${v.control.n}. `}
                  Spent {money(v.spent_usd)}.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * The investigation fleet on a live run: one button to start it, what it does one hover away, then its
 * log as it lands. Lanes for the
 * investigators, the coordinator's picks and the critic's challenges, and the tested plan with a
 * re-check on each fix. Everything shown is folded from the fleet's own event log.
 */
export function FleetPanel({ run }: { run: Run }) {
  const [fleets, setFleets] = useState<FleetSummary[]>([]);
  const [estimate, setEstimate] = useState<FleetEstimate | null>(null);
  const [view, setView] = useState<FleetView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveOk, setLiveOk] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [checking, setChecking] = useState<number | null>(null);
  const stop = useRef<(() => void) | null>(null);
  const live = run.mode === "live_api";

  const follow = useCallback((id: string, after = 0) => {
    stop.current?.();
    stop.current = streamFleet(id, after, (e) => setView((v) => fold(v ?? emptyView(id), e)),
      () => getFleets(run.id).then((r) => setFleets(r.fleets))
        .catch((e: Error) => setError(`Could not refresh the list of fleets: ${e.message}`)),
      (e) => setError(e.message));
  }, [run.id]);

  useEffect(() => {
    if (!live) return;
    // without a health reading live stays off, so no fleet is offered that the API could not start
    getHealth().then((h) => setLiveOk(!!h.live_available)).catch(() => {});
    getFleets(run.id).then((r) => {
      setFleets(r.fleets); setEstimate(r.estimate);
      if (r.fleets[0]) { setView(emptyView(r.fleets[0].id)); follow(r.fleets[0].id); }
    }).catch((e: Error) => setError(`Could not load this run's fleets: ${e.message}`));
    return () => stop.current?.();
  }, [run.id, live, follow]);

  const runningNow = !!view && !view.done;
  useEffect(() => {
    if (!runningNow) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [runningNow]);

  if (!live) return null;

  const start = () => {
    setError(null);
    startFleet(run.id).then(({ id }) => { setView(emptyView(id)); follow(id); }).catch((e: Error) => setError(e.message));
  };
  const check = (rank: number) => {
    if (!view) return;
    setChecking(rank);
    streamVerify(view.id, rank, (e) => setView((v) => (v ? fold(v, e) : v)), () => setChecking(null),
      (e) => { setError(e.message); setChecking(null); });
  };

  const t0 = view?.t0 ?? now;
  const end = view?.done && view.t0 != null && view.done.wall_s != null ? view.t0 + view.done.wall_s * 1000 : now;
  const decided = view?.lanes.filter((l) => l.status === "finished" || l.status === "failed").length ?? 0;
  return (
    <section className="panel-sec fleet-panel" aria-live="polite">
      {view && (
        <div className="panel-sec-head" data-tour="ev-investigate">
          <h3><Term k="investigation_fleet">Investigate the gaps</Term></h3>
          <span className="block-found">
            {view.done
              ? `${plural(view.lanes.length, "investigation")} · ${minutes(view.done.wall_s ?? 0)} · ${money(view.done.spent_usd ?? view.spent)} of ${money(view.budget ?? 0)}`
              : `${decided} of ${plural(view.lanes.length, "investigation")} done · ${money(view.spent)} spent`}
          </span>
        </div>
      )}
      {(!view || view.done) && (
        <div className="fleet-start" data-tour="ev-investigate">
          <button className="primary" type="button" onClick={start} disabled={!liveOk || runningNow || run.read_only}>
            {view ? "Investigate again" : "Investigate the gaps"}
            {estimate && ` (≈ ${money(estimate.usd)}, ≈ ${estimate.minutes} min)`}
          </button>
          <Term k="investigation_fleet" icon note={estimate
            && `${plural(estimate.candidates, "claim")} on the shortlist; it spends at most ${money(estimate.budget_usd)}.${liveOk ? "" : " Needs a live model."}`} />
          <span className="muted">{run.read_only ? READ_ONLY_NOTE : `${PROVENANCE_LABEL.counterfactual_replay}: nothing here moves a score.`}</span>
        </div>
      )}
      {error && <div className="callout error">{error}</div>}
      {view?.stopped && <div className="callout">{view.stopped}</div>}
      {view && view.lanes.length + view.skipped.length > 0 && (
        <>
          <h4>The coordinator's picks</h4>
          <ul className="fleet-picks">
            {view.lanes.filter((l) => l.task.try_no === 1).map((l) => (
              <li key={l.task.id}>▶ <b>{l.task.claim}</b> on “{l.task.question}”: {l.task.reason}</li>
            ))}
            {view.skipped.map((s, i) => <li key={i} className="muted">⏸ <b>{s.claim}</b>: {s.reason}</li>)}
          </ul>
          {view.rejected.length > 0 && (
            <details className="fleet-rejected">
              <summary>{plural(view.rejected.length, "call")} our code refused</summary>
              <ul>{view.rejected.map((r, i) => <li key={i}>{r.call}: {r.reason}</li>)}</ul>
            </details>
          )}
          <h4>Investigators</h4>
          <ol className="fleet-lanes">{view.lanes.map((l) => <LaneRow key={l.task.id} l={l} t0={t0} now={end} />)}</ol>
        </>
      )}
      {view?.plan && (
        <>
          <h4><Term k="tested_plan">The tested plan</Term></h4>
          <ol className="plan-list">
            {view.plan.items.map((i) => (
              <PlanCard key={i.rank} i={i} check={view.checks[i.rank]} running={checking != null} onCheck={() => check(i.rank)} />
            ))}
          </ol>
          <p className="muted why-foot">
            Predictions are replays of what AI read ({PROVENANCE_LABEL.counterfactual_replay.toLowerCase()}); a re-check
            is measured live. Lines {!view.plan.written_by || view.plan.written_by === "template" ? "written by our templates" : `worded by ${view.plan.written_by}, checked by our code`}.
            {view.plan.notes.map((n) => ` ${n}`)}
          </p>
        </>
      )}
      {fleets.some((f) => f.id !== view?.id) && (
        <p className="muted why-foot fleet-others">
          Other fleets on this run:{" "}
          {fleets.filter((f) => f.id !== view?.id).map((f) => (
            <button key={f.id} type="button" className="linky" onClick={() => { setView(emptyView(f.id)); follow(f.id); }}>
              {f.created_at ? when(f.created_at) : ""} · {plural(f.tasks, "task")} · {money(f.spent_usd)}
            </button>
          ))}
        </p>
      )}
    </section>
  );
}
