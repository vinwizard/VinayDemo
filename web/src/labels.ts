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

/**
 * "50% of pages (3 of 6)". A percentage of six pages is not the same claim as a percentage of
 * sixty, so the count travels with it everywhere the share is shown.
 */
export function statedOn(pages: number, total: number): string {
  if (!total) return "no page data";
  return `${Math.round((pages / total) * 100)}% of pages (${pages} of ${total})`;
}

/**
 * How much of the site states an attribute, or null when nothing is known. Every report surface
 * goes through here so two halves of one row cannot disagree: a run saved before the counts existed
 * has claim_strength but no claim_pages, and "no page data" is false for it — that strength was
 * itself derived from page counts, it just cannot show them.
 */
export function claimShare(pages: number, total: number, strength: number | null): string | null {
  if (total) return statedOn(pages, total);
  return strength == null ? null : `${Math.round(strength * 100)}% of pages`;
}

/** `Probe.kind`: what the question does, not what the enum is called. */
export const PROBE_KIND_LABEL: Record<string, string> = {
  named: "names your brand",
  blind: "buyer search",
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
 * different order.
 */
export function probeLabels(probes: Probe[], topics: Topic[] = []): Record<string, string> {
  const topicLabel = new Map(topics.map((t) => [t.id, t.label]));
  return Object.fromEntries(
    probes.map((p) => [p.id, streamingProbeLabel(p.id, p.kind, p.phase, topicLabel.get(p.topic_id))]),
  );
}

/** Live-feed name for one answer, where only the probe id, kind and topic label have arrived yet. */
export function streamingProbeLabel(probeId: string, kind: string, phase: string, topic?: string | null) {
  const n = idNumber(probeId);
  const suffix = topic ? ` — ${topic}` : "";
  // The adaptive comparison question is the one probe that is not an nth of anything — exactly one
  // per run, with an id that carries no number — so it is named rather than numbered.
  if (kind === "named") return phase === "followup" ? "Comparison question" : `Brand question ${n ?? "?"}`;
  if (phase === "followup") return `Follow-up question ${n ?? "?"}${suffix}`;
  return `Buyer question ${n ?? "?"}${suffix}`;
}

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });

export interface RunLabel { short: string; full: string }

/**
 * Hex run ids ("d428e213e6") name nothing. Number runs in the order they were made — oldest is
 * Run 1, with the scenario, because every bundled run shares one company name and Compare exists to
 * tell them apart. Callers keep the raw id as a tooltip so a run is still findable on disk.
 */
export function runLabels(runs: RunSummary[]): Record<string, RunLabel> {
  const oldestFirst = [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const out: Record<string, RunLabel> = {};
  oldestFirst.forEach((r, i) => {
    const short = `Run ${i + 1}`;
    const scenario = r.scenario ? ` · Scenario ${r.scenario}` : "";
    out[r.id] = { short, full: `${short}${scenario} · ${when(r.created_at)} · ${r.company}` };
  });
  return out;
}
