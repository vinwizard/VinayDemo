// The one place raw engine identifiers become words a reader who has never seen the code can read.
// Nothing here changes stored data: ids, provenance values and strengths keep their names in the
// JSON exports and saved runs. This module only decides how they are SPOKEN on screen.
import type { Probe, RunSummary, Topic, Zone } from "./api";

// Zone names are spoken as the opportunity each one is, not as a loss: the zone keys, counts and
// every number behind them are unchanged — only the words on screen are. Each label reads alone on a
// pill and before a count ("claim to win back · 2").
export const ZONE_LABEL: Record<Zone, string> = {
  landed: "landed",
  lost_claim: "claim to win back",
  contested: "claim to correct",
  // The zone fires below drift.CLAIM_THRESHOLD, a share of pages, so it covers "1 of 6" as well as
  // "0 of 6": the wording must not say "never stated" beside a row reading "2 of 6".
  unstated_intent: "claim to amplify",
  imposed: "identity to shape",
  unprioritised: "unweighted echo",
};

/** One line per zone, for the legend above the claim table. */
export const ZONE_MEANING: Record<Zone, string> = {
  landed: "you want it, and AI already says it",
  lost_claim: "your site says it; AI does not repeat it yet",
  contested: "AI tells a different story from your claim — room to set it straight",
  unstated_intent: "you want it; more of your pages could say it",
  imposed: "AI already links you to it, though you never claimed it — adopt it or reframe it",
  unprioritised: "your site says it and AI repeats it; you just have not weighted it",
};

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

/**
 * A model answer as plain text. Answers are Markdown written by an untrusted model, so the markup is
 * stripped rather than rendered: nothing from an answer ever becomes HTML or a link. A link keeps its
 * text, even when an excerpt cut it off before the closing parenthesis; list items keep a bullet.
 */
export const plain = (md: string) => md
  .replace(/\[([^\]]*)\]\([^)\s]*\)?/g, "$1")
  .replace(/^[ \t]*#{1,6}[ \t]+/gm, "")
  .replace(/^([ \t]*)[-*+][ \t]+/gm, "$1• ")
  .replace(/\*+|__|`+/g, "");

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
  if (kind === "named") return phase === "followup" ? "Comparison question" : `Branded question ${n ?? "?"}`;
  if (phase === "control") return "Control question";
  if (phase === "followup") return `Follow-up question ${n ?? "?"}${suffix}`;
  return `Unbranded question ${n ?? "?"}${suffix}`;
}

export const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

export const when = (iso: string) =>
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

const tenth = (x: number) => Math.round(x * 10) / 10;

export interface Headline {
  label: string;
  /** The real score: the share AI already says. Never hidden, only placed under the potential. */
  value: number | null;
  /** 100 minus the score: the share still open. Display only — nothing stores it. */
  potential: number | null;
  /** The real score as one sentence, shown directly beneath the potential. */
  today: string | null;
  /** The key the server's na_reasons uses for this number. */
  field: "claim_echo" | "alignment";
}

/**
 * The run's headline, framed as upside: claim echo when nothing was weighted, alignment otherwise.
 * The large number is what AI does NOT yet say; the real score sits right under it.
 */
export function headline(d: { lens?: string | null; alignment: number | null; claim_echo?: number | null }): Headline {
  const claim = d.lens === "claim";
  const value = claim ? d.claim_echo ?? null : d.alignment;
  return {
    label: claim ? "Claim echo" : "Alignment",
    value,
    potential: value == null ? null : tenth(100 - value),
    today: value == null ? null
      : claim ? `AI echoes ${value}% of what you claim today`
      : `AI says ${value}% of what you want to be known for today`,
    field: claim ? "claim_echo" : "alignment",
  };
}

export const pctText = (x: number | null | undefined) => (x == null ? "n/a" : `${x}%`);

/** "78.6% untapped potential", or "n/a" when the server withheld the score. */
export const potentialText = (h: Headline) =>
  h.potential == null ? "n/a" : `${h.potential}% untapped potential`;
