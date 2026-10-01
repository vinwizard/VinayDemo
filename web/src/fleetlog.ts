// A fleet's event log folded into what the fleet panel shows (fleet.tsx). Pure, so a reload that replays
// the log from its first line lands exactly where the live stream left off.
// The fleet's records, mirroring schemas.py (FleetTask, Challenge, PlanItem, ActionPlan, Verification,
// FleetEvent) — keep in sync. They live here, not in api.ts, so `node --test` can type-check this file.
import { instant } from "./time.ts";

/** One investigator's job, as the coordinator (or code, when it could not) dispatched it. */
export interface FleetTask {
  id: string; attribute_id: string; claim: string; probe_id: string; question: string; term: string | null;
  reason: string; budget_usd: number; try_no: number; parent: string | null; by: "model" | "code";
}
/** The critic's objection to one finished investigation: code rules, never a model. */
export interface Challenge {
  task_id: string;
  kind: "thin" | "ceiling" | "floor" | "not_reproducible" | "off_claim" | "contradicts";
  ask: "other_question" | "more_budget" | "accept";
  text: string; evidence: string[];
}
/** One line of the tested plan. Every number is copied from an experiment of the investigation it cites. */
export interface PlanItem {
  rank: number; attribute_id: string; claim: string;
  fix: "copy" | "authority" | "source" | "none" | "thin" | "untested";
  text: string; page_url: string | null; rewrite: string | null; hypothetical: boolean; sources: string[];
  question: string | null; task_id: string | null; investigation_id: string | null; arm_id: string | null;
  k: number; n: number; base_k: number; base_n: number; effect: number | null; interval: [number, number] | null;
  notes: string[];
}
export interface ActionPlan {
  items: PlanItem[]; written_by?: string; provenance: "counterfactual_replay"; notes: string[];
}
/** A fix re-checked once it is live: `live` is measured; the prediction and `control` are replays. */
export interface Verification {
  /** Null on a quick win's replay test, whose re-check is kept on its investigation. */
  fleet_id: string | null; rank: number | null; attribute_id: string; claim: string; page_url: string; copy_text: string;
  question: string; investigation_id: string; created_at: string;
  page_has_copy: boolean | null; page_note: string;
  read_by_ai: { k: number; n: number }; live: { k: number; n: number }; live_provenance: "live_api";
  live_quotes: string[]; control: { k: number; n: number };
  predicted: { k: number; n: number }; base: { k: number; n: number };
  verdict: "not_published" | "not_crawled" | "confirmed" | "not_confirmed" | "undecided" | "model_moved" | "budget";
  text: string; budget_usd: number; spent_usd: number;
}
/** One line of a fleet's append-only log. */
export interface FleetEvent {
  seq: number; at: string; task_id: string | null; spent_usd: number;
  kind: "started" | "turn" | "dispatched" | "rejected" | "skipped" | "began" | "progress" | "arm"
    | "finished" | "failed" | "cancelling" | "challenged" | "accepted" | "planned" | "verify"
    | "verified" | "stopped" | "done";
  data: Record<string, any>;
}

/** One investigator as the log tells it. */
export interface Lane {
  task: FleetTask;
  began: number | null;
  ended: number | null;
  status: "waiting" | "running" | "cancelling" | "finished" | "failed" | "skipped";
  last: string | null;
  arms: number;
  verdicts: { kind: string; text: string }[];
  challenges: Challenge[];
  decided: string | null;
  error: string | null;
  spent: number | null;
}

/** A fleet as its log tells it: `fold` over every event, in order. */
export interface FleetView {
  id: string;
  t0: number | null;
  budget: number | null;
  lanes: Lane[];
  skipped: { claim: string; reason: string; by: string }[];
  rejected: { call: string; reason: string }[];
  plan: ActionPlan | null;
  checks: Record<number, { log: string[]; v: Verification | null; error: string | null }>;
  done: { status: string; wall_s?: number; spent_usd?: number } | null;
  stopped: string | null;
  spent: number;
  seq: number;
}

export const emptyView = (id: string): FleetView => ({
  id, t0: null, budget: null, lanes: [], skipped: [], rejected: [], plan: null, checks: {},
  done: null, stopped: null, spent: 0, seq: 0,
});

const time = (at: string) => instant(at).getTime();

/** Pure: the same log always gives the same view, so a reload replays to where the stream left off. */
export function fold(v: FleetView, e: FleetEvent): FleetView {
  if (e.seq <= v.seq) return v;
  const next: FleetView = { ...v, seq: e.seq, spent: Math.max(v.spent, e.spent_usd) };
  const lane = (id: string | null) => next.lanes.find((l) => l.task.id === id);
  const set = (id: string | null, patch: Partial<Lane>) => {
    next.lanes = next.lanes.map((l) => (l.task.id === id ? { ...l, ...patch } : l));
  };
  const d = e.data;
  switch (e.kind) {
    case "started": next.t0 = time(e.at); next.budget = d.budget_usd; break;
    case "dispatched":
      next.lanes = [...next.lanes, { task: d.task, began: null, ended: null, status: "waiting", last: null, arms: 0,
        verdicts: [], challenges: [], decided: null, error: null, spent: null }];
      break;
    case "rejected": next.rejected = [...next.rejected, { call: d.call, reason: d.reason }]; break;
    case "skipped":
      if (e.task_id) set(e.task_id, { status: "skipped", last: d.reason });
      else next.skipped = [...next.skipped, { claim: d.claim, reason: d.reason, by: d.by }];
      break;
    case "began": set(e.task_id, { began: time(e.at), status: "running" }); break;
    case "progress": set(e.task_id, { last: d.text }); break;
    case "arm": set(e.task_id, { arms: (lane(e.task_id)?.arms ?? 0) + (d.arm?.kind === "base" ? 0 : 1) }); break;
    case "cancelling": set(e.task_id, { status: "cancelling" }); break;
    case "finished":
      set(e.task_id, { ended: time(e.at), status: "finished", verdicts: d.verdicts, spent: d.spent_usd });
      break;
    case "failed": set(e.task_id, { ended: time(e.at), status: "failed", error: d.error }); break;
    case "challenged": set(e.task_id, { challenges: [...(lane(e.task_id)?.challenges ?? []), d.challenge] }); break;
    case "accepted": set(e.task_id, { decided: d.reason ? `accepted: ${d.reason}` : "accepted" }); break;
    case "planned": next.plan = d.plan; break;
    case "verify": {
      const c = next.checks[d.rank] ?? { log: [], v: null, error: null };
      next.checks = { ...next.checks, [d.rank]: { ...c, log: [...c.log, d.text], error: d.error ? d.text : c.error } };
      break;
    }
    case "verified": {
      const c = next.checks[d.rank] ?? { log: [], v: null, error: null };
      next.checks = { ...next.checks, [d.rank]: { ...c, v: d.verification } };
      break;
    }
    case "stopped": next.stopped = d.reason; break;
    case "done": next.done = { status: d.status, wall_s: d.wall_s, spent_usd: d.spent_usd }; break;
  }
  // a re-dispatch closes the task it follows up
  if (e.kind === "dispatched" && d.task.parent) set(d.task.parent, { decided: `re-dispatched as ${d.task.id}` });
  return next;
}
