// Typed client for the Python engine's HTTP API. Mirrors schemas.py — keep in sync.
export const API = "http://127.0.0.1:8000";

export type Zone = "landed" | "lost_claim" | "unstated_intent" | "imposed";
export type Owner = "authority_gap" | "messaging_gap" | "imposed_identity" | "none";

export interface AttributeScore {
  attribute_id: string;
  label: string;
  intended_weight: number | null;
  claim_strength: number | null;
  n: number;
  echoes: number;
  echo_rate: number | null;
  negative_echoes: number;
  zone: Zone;
  owner: Owner;
  quotes: string[];
  probe_ids: string[];
  limitations: string[];
}

export interface DriftReport {
  provenance: string;
  n_named: number;
  n_blind: number;
  alignment: number | null;
  visibility: number | null;
  landed: string[];
  lost_claims: string[];
  imposed: string[];
  unstated_intent: string[];
  scores: AttributeScore[];
  limitations: string[];
}

export interface Probe {
  id: string;
  topic_id: string;
  text: string;
  kind: "blind" | "named";
  phase: string;
  purpose: string;
}

export interface Answer {
  probe_id: string;
  text: string;
  citations: string[];
  provenance: string;
  status: string;
}

export interface Run {
  id: string;
  created_at: string;
  scenario: string | null;
  status: string;
  mode: string;
  profile: { name: string; domain: string };
  probes: Probe[];
  answers: Answer[];
  attribute_scores: AttributeScore[];
  drift: DriftReport | null;
  log: string[];
}

export interface RunSummary {
  id: string;
  created_at: string;
  scenario: string | null;
  status: string;
  company: string;
  alignment: number | null;
  visibility: number | null;
  landed: number;
  lost: number;
  unstated: number;
  imposed: number;
}

export interface Scenario {
  id: string;
  title: string;
  notice: string | null;
  company: string;
  named_probes: number;
  intended: { id: string; label: string; weight: number; claim_pages: number; claim_pages_total: number }[];
}

export const ZONE_LABEL: Record<Zone, string> = {
  landed: "landed",
  lost_claim: "lost claim",
  unstated_intent: "never stated",
  imposed: "imposed",
};

export const OWNER_TITLE: Record<Owner, string> = {
  authority_gap: "Authority gap",
  messaging_gap: "Messaging gap",
  imposed_identity: "Imposed identity",
  none: "Aligned",
};

// Why each gap is whose problem. Mirrors drift.OWNER_TEXT.
export const OWNER_TEXT: Record<Owner, string> = {
  authority_gap: "You state this clearly and the models are not repeating it.",
  messaging_gap: "AI does not say it because your own copy does not clearly say it either.",
  imposed_identity: "AI asserts this about you without you claiming it.",
  none: "Intended positioning is reflected in AI answers.",
};

export const ZONE_ORDER: Record<Zone, number> = {
  lost_claim: 0,
  unstated_intent: 1,
  imposed: 2,
  landed: 3,
};

async function json<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${path}`);
  return r.json();
}

export const getScenarios = () => json<Scenario[]>("/api/scenarios");
export const getRuns = () => json<RunSummary[]>("/api/runs");
export const getRun = (id: string) => json<Run>(`/api/runs/${id}`);

export interface StreamHandlers {
  onNode?: (e: { node: string; stage: string; agent: string; log: string }) => void;
  onAnswer?: (e: { probe_id: string; kind: string; phase: string; text: string; done: number; expected: number }) => void;
  onDone?: (e: { run_id: string; run: Run }) => void;
  onError?: (e: { message: string }) => void;
}

/** Opens the SSE stream for one run. Returns a closer so the caller can abort. */
export function streamRun(scenario: string, h: StreamHandlers): () => void {
  const es = new EventSource(`${API}/api/stream?scenario=${encodeURIComponent(scenario)}`);
  const on = (name: string, fn?: (d: never) => void) =>
    es.addEventListener(name, (ev) => fn?.(JSON.parse((ev as MessageEvent).data)));
  on("node", h.onNode as never);
  on("answer", h.onAnswer as never);
  on("done", ((d: { run_id: string; run: Run }) => {
    h.onDone?.(d);
    es.close(); // the server ends the response; close so the browser does not reconnect
  }) as never);
  on("error", ((d: { message: string }) => {
    h.onError?.(d);
    es.close();
  }) as never);
  es.onerror = () => es.close(); // transport-level failure: EventSource would otherwise retry forever
  return () => es.close();
}
