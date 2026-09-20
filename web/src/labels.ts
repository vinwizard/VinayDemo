// The one place raw engine identifiers become words a reader who has never seen the code can read.
// Nothing here changes stored data: ids, provenance values and strengths keep their names in the
// JSON exports and saved runs. This module only decides how they are SPOKEN on screen.
import type { Probe, RunSummary, Topic } from "./api";

/** `Answer.provenance`, `DriftReport.provenance` and `Run.mode` all speak this vocabulary. */
export const PROVENANCE_LABEL: Record<string, string> = {
  synthetic: "Sample data",
  demo_replay: "Sample run",
  live_api: "Measured live",
  page_fetch: "From their website",
  user_provided: "You told us",
  web_research_snapshot: "Research snapshot",
};

export const provenanceLabel = (v: string | null | undefined) =>
  (v && PROVENANCE_LABEL[v]) || v || "unknown";

/** `Probe.kind`: what the question does, not what the enum is called. */
export const PROBE_KIND_LABEL: Record<string, string> = {
  named: "names your brand",
  blind: "buyer search",
};

/** `TopicEvaluation.status`. */
export const TOPIC_STATUS_LABEL: Record<string, string> = {
  "candidate gap": "Not recommended",
  mixed: "Split results",
  "observed presence": "Found",
};

/** The number a probe id already carries: np-3 -> 3, ai_native-b1 -> 1, kb-f2 -> 2. */
const idNumber = (id: string): number | null => {
  const m = /(\d+)$/.exec(id);
  return m ? Number(m[1]) : null;
};

/**
 * id -> human name, for every probe in a run.
 *
 * Numbering comes from the id itself, so "Brand question 3" is the same question on every screen and
 * in every rerender; array position would renumber the moment the engine planned probes in a
 * different order. Ids with no trailing number fall back to their rank in id order — still stable,
 * still independent of how the array happened to arrive.
 */
export function probeLabels(probes: Probe[], topics: Topic[] = []): Record<string, string> {
  const topicLabel = new Map(topics.map((t) => [t.id, t.label]));
  const out: Record<string, string> = {};
  for (const kind of ["named", "blind"]) {
    const group = probes.filter((p) => p.kind === kind).sort((a, b) => a.id.localeCompare(b.id));
    group.forEach((p, i) => {
      const n = idNumber(p.id) ?? i + 1;
      const topic = topicLabel.get(p.topic_id);
      if (kind === "named") out[p.id] = `Brand question ${n}`;
      else if (p.phase === "followup") out[p.id] = `Follow-up question ${n}${topic ? ` — ${topic}` : ""}`;
      else out[p.id] = `Buyer question ${n}${topic ? ` — ${topic}` : ""}`;
    });
  }
  return out;
}

/** Live-feed name for one answer, where only the probe id, kind and topic label have arrived yet. */
export function streamingProbeLabel(probeId: string, kind: string, phase: string, topic?: string | null) {
  const n = idNumber(probeId);
  const suffix = topic ? ` — ${topic}` : "";
  if (kind === "named") return `Brand question ${n ?? "?"}`;
  if (phase === "followup") return `Follow-up question ${n ?? "?"}${suffix}`;
  return `Buyer question ${n ?? "?"}${suffix}`;
}

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });

export interface RunLabel { short: string; full: string; hash: string }

/**
 * Hex run ids ("d428e213e6") name nothing. Number runs in the order they were made — oldest is
 * Run 1 — and keep the hash as a tooltip so a run is still findable on disk by its real name.
 */
export function runLabels(runs: RunSummary[]): Record<string, RunLabel> {
  const oldestFirst = [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const out: Record<string, RunLabel> = {};
  oldestFirst.forEach((r, i) => {
    const short = `Run ${i + 1}`;
    out[r.id] = { short, full: `${short} · ${when(r.created_at)} · ${r.company}`, hash: r.id };
  });
  return out;
}
