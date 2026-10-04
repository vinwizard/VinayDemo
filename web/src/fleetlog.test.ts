// The fleet panel's fold over its event log, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { test } from "node:test";
import type { FleetEvent } from "./fleetlog.ts";
import { emptyView, fold } from "./fleetlog.ts";

let seq = 0;
const ev = (kind: FleetEvent["kind"], data: Record<string, unknown> = {}, task_id: string | null = null,
  at = "2026-09-28T20:00:00"): FleetEvent => ({ seq: ++seq, at, kind, task_id, data, spent_usd: seq / 100 });
const task = (id: string, extra: Record<string, unknown> = {}) => ({
  task: { id, attribute_id: "fast", claim: "Fast shipping", probe_id: "np-1", question: "What is Acme?", term: null,
          reason: "Worth it.", budget_usd: 0.6, try_no: 1, parent: null, by: "model", ...extra },
});

test("a lane runs, finishes, is challenged, and its re-dispatch closes it", () => {
  seq = 0;
  const log = [
    ev("started", { budget_usd: 3 }),
    ev("dispatched", task("t1")),
    ev("began", {}, "t1", "2026-09-28T20:00:01"),
    ev("progress", { text: "Asking live 3 times." }, "t1"),
    ev("arm", { arm: { kind: "base" } }, "t1"),
    ev("arm", { arm: { kind: "edit" } }, "t1"),
    ev("finished", { verdicts: [{ kind: "not_reproducible", text: "No." }], investigation_id: "i1", spent_usd: 0.2 }, "t1",
       "2026-09-28T20:02:00"),
    ev("challenged", { challenge: { task_id: "t1", kind: "not_reproducible", ask: "other_question", text: "Again.", evidence: [] } }, "t1"),
    ev("dispatched", task("t2", { parent: "t1", try_no: 2, probe_id: "np-2" })),
  ];
  const v = log.reduce(fold, emptyView("f1"));
  const [t1, t2] = v.lanes;
  assert.equal(t1.status, "finished");
  assert.equal(t1.arms, 1);                       // the base is not an experiment
  assert.equal(t1.ended! - t1.began!, 119_000);
  assert.equal(t1.challenges[0].kind, "not_reproducible");
  assert.equal(t1.decided, "re-dispatched as t2");
  assert.equal(t2.status, "waiting");
  assert.equal(v.spent, log[log.length - 1].spent_usd);
});

test("an event already folded is ignored, so a resumed stream never double counts", () => {
  seq = 0;
  const log = [ev("started", { budget_usd: 3 }), ev("dispatched", task("t1")), ev("arm", { arm: { kind: "edit" } }, "t1")];
  const once = log.reduce(fold, emptyView("f1"));
  const twice = log.reduce(fold, once);
  assert.equal(twice.lanes.length, 1);
  assert.equal(twice.lanes[0].arms, 1);
});

test("the plan, a re-check and the end land where the panel reads them", () => {
  seq = 0;
  const plan = { items: [{ rank: 1, fix: "copy" }], provenance: "counterfactual_replay", notes: [] };
  const v = [
    ev("started", { budget_usd: 3 }),
    ev("planned", { plan }),
    ev("done", { status: "complete", wall_s: 384.7, spent_usd: 1.07 }),
    ev("verify", { rank: 1, text: "acme.com/about does not carry the new copy word for word yet." }),
    ev("verified", { rank: 1, verification: { verdict: "not_published" } }),
  ].reduce(fold, emptyView("f1"));
  assert.equal(v.plan?.items[0].rank, 1);
  assert.deepEqual(v.done, { status: "complete", wall_s: 384.7, spent_usd: 1.07 });
  assert.equal(v.checks[1].log.length, 1);
  assert.equal(v.checks[1].v?.verdict, "not_published");
});
