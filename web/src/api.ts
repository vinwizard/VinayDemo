// Typed client for the Python engine's HTTP API. Mirrors schemas.py — keep in sync.
// VITE_API lets a second checkout run beside the first without fighting over port 8000.
export const API: string = import.meta.env.VITE_API ?? "http://127.0.0.1:8000";

export type Zone = "landed" | "lost_claim" | "contested" | "unstated_intent" | "imposed" | "unprioritised";
export type Owner = "authority_gap" | "messaging_gap" | "contested_identity" | "imposed_identity"
  | "unprioritised_claim" | "none";

export interface AttributeScore {
  attribute_id: string;
  label: string;
  /** Emergent: found in the answers by the discovery pass, never supplied by you or your site. */
  discovered: boolean;
  description: string | null;
  intended_weight: number | null;
  claim_strength: number | null;
  claim_pages: number;
  claim_pages_total: number;
  n: number;
  echoes: number;
  echo_rate: number | null;
  negative_echoes: number;
  mention_rate: number | null;
  negative_rate: number | null;
  zone: Zone;
  owner: Owner;
  quotes: string[];
  probe_ids: string[];
  limitations: string[];
  /** Field name -> why that number is null. */
  na_reasons?: Record<string, string>;
}

export interface DriftReport {
  provenance: string;
  n_named: number;
  n_blind: number;
  named_asked: number;
  excluded_named: number;
  excluded_reasons: string[];
  /** claim: nothing weighted, the site's own claims are the reference. intent: weights exist. */
  lens?: "claim" | "intent";
  /** Headline: prominence-weighted share of the site's claims AI repeats supportively. */
  claim_echo?: number | null;
  alignment: number | null;
  /** Buyer visibility: the mean over questions, each worth the mean of its own tries. */
  visibility: number | null;
  /** How many times a repeat-sampled question was asked. Absent on runs saved before repeats: once. */
  tries?: number;
  /** How many buyer questions were asked more than once. */
  repeat_sample?: number;
  /** The wobble, not a second estimate: [lowest, highest] visibility of the repeat-sampled
   * questions alone, try by try. How sure the whole number is lives in `visibility_interval`. */
  visibility_range?: [number, number] | null;
  /** Why this visibility is not trusted (its control question), or null. Set with one set only. */
  low_confidence?: string | null;
  /** Buyer visibility per front, side by side. Absent on runs saved before fronts. */
  sets?: VisibilitySet[];
  placed_category?: string | null;
  aiming_category?: string | null;
  /** Where AI places you minus where you aim to be, when both were measured. */
  visibility_gap?: number | null;
  /** Bootstrap 95% confidence intervals [low, high]; why one is missing: na_reasons["<field>_interval"]. */
  visibility_interval?: [number, number] | null;
  gap_interval?: [number, number] | null;
  /** The gap's interval excludes 0: a real gap, not the noise of this sample. */
  gap_real?: boolean | null;
  claim_echo_interval?: [number, number] | null;
  alignment_interval?: [number, number] | null;
  /** "placed" / "aiming" -> why that front was not measured. */
  missing_fronts?: Record<string, string>;
  landed: string[];
  lost_claims: string[];
  contested: string[];
  imposed: string[];
  unstated_intent: string[];
  unprioritised: string[];
  scores: AttributeScore[];
  limitations: string[];
  /** Field name -> why that number is null. */
  na_reasons?: Record<string, string>;
}

/** placed: the category AI's brand answers most associate with the company. aiming: its site's
 * own core category. both: the same category, asked once. null: one unlabelled set (replay). */
export type Front = "placed" | "aiming" | "both" | null;

/** Buyer visibility on one front, with its repeat sample, wobble and control question. */
export interface VisibilitySet {
  front?: Front;
  category?: string | null;
  visibility: number | null;
  tries?: number;
  visibility_range?: [number, number] | null;
  n_blind: number;
  questions: number;
  repeat_sample?: number;
  control_probe_id?: string | null;
  low_confidence?: string | null;
  /** Bootstrap 95% confidence interval of `visibility`, or why there is none. */
  interval?: [number, number] | null;
  interval_note?: string | null;
}

export interface Topic {
  id: string;
  label: string;
  kind: "buyer" | "perception" | "control";
  front?: Front;
  buyer_need: string;
  fit: string;
}

/** Where a buyer question came from when it is a real search, not one AI wrote. */
export interface Demand {
  /** The real search, verbatim: the question asked. */
  phrase: string;
  source: "autocomplete" | "reddit";
  /** Every real phrasing grouped with it, the phrase included. */
  phrasings: { text: string; source: "autocomplete" | "reddit" }[];
}

export interface Probe {
  id: string;
  topic_id: string;
  text: string;
  kind: "blind" | "named";
  phase: string;
  purpose: string;
  demand?: Demand | null;
}

export interface Answer {
  probe_id: string;
  text: string;
  citations: string[];
  provenance: string;
  status: string;
  provider: string | null;
  model: string | null;
  collected_at: string | null;
  search_executed: boolean | null;
  evaluator_model?: string | null;
  try_no?: number;
}

export interface QueryEvaluation {
  probe_id: string;
  valid: boolean;
  mentioned: boolean;
  recommended: boolean;
  negative_mention: boolean;
  competitor_recommendations: string[];
  explanation: string;
  /** The validator's notes, e.g. "Off-topic answer." */
  warnings?: string[];
  try_no?: number;
}

export interface TopicEvaluation {
  topic_id: string;
  phase: string;
  n: number;
  recommendations: number;
  top_competitors: string[];
}

/** How to win it back: one verified fix per claim to win back or amplify. Moves no number. */
export interface WinBackAction {
  attribute_id: string;
  label: string;
  zone: Zone;
  page_url: string;
  /** Verbatim on that page; null means add new copy. */
  current_copy: string | null;
  rewrite: string;
  question_ids: string[];
  why: string;
  provenance: string;
}

export interface Run {
  id: string;
  created_at: string;
  scenario: string | null;
  status: string;
  mode: string;
  profile: { name: string; domain: string; logo_url?: string | null; core_category?: string | null;
             positioning_points?: { text: string }[] };
  topics: Topic[];
  probes: Probe[];
  /** Per front: how many buyer questions are real searches, or why none are. Absent before grounding. */
  demand_notes?: string[];
  answers: Answer[];
  evaluations: QueryEvaluation[];
  /** Buyer questions asked again (try 2 onward); absent on runs saved before repeats. */
  repeat_answers?: Answer[];
  repeat_evaluations?: QueryEvaluation[];
  topic_evaluations: TopicEvaluation[];
  attributes?: ClaimedAttribute[];
  attribute_scores: AttributeScore[];
  drift: DriftReport | null;
  /** Absent on runs saved before the action plan existed. */
  win_back?: WinBackAction[];
  win_back_notes?: string[];
  /** Simulated retrieval and the fixes re-scored; absent on runs saved before it existed. */
  retrieval?: RetrievalSim | null;
  /** The positioning map; absent on runs saved before it existed. */
  positioning?: PositioningMap | null;
  /** The company's site audit when the run started; absent on replays and older runs. */
  audit?: SiteAudit | null;
  log: string[];
  insights?: Insights;  // derived by the API from the saved answers; absent on a run read raw
}

/** One passage and how closely it matches a buyer question or search: cosine similarity of embeddings. */
export interface ScoredPassage { url: string; text: string; score: number; query: string }
export interface Reask { named: boolean; answer: string; model: string; collected_at: string }
export interface RetrievalRow {
  probe_id: string; queries: number;
  yours: ScoredPassage | null; rival: ScoredPassage | null; fixed: ScoredPassage | null;
  fix_attribute_id: string | null; reask: Reask | null;
}
/** A mini version of how an AI search picks what to read (retrieval.py). Moves no score. */
export interface RetrievalSim {
  provenance: string; model: string | null; pages: number; passages: number;
  rows: RetrievalRow[]; skipped: string[];
}

/** One dot on the positioning map: the mean embedding of the sentences it was built from. */
export interface MapPoint {
  name: string; kind: "seen" | "intended" | "rival"; x: number; y: number;
  sentences: string[]; similarity: number | null;
}
/** Where AI places the brand, its rivals and where it aims (positioning.py): a similarity picture, no score. */
export interface PositioningMap {
  provenance: string; model: string | null; aim?: "intended" | "site"; points: MapPoint[];
  x_axis: string[]; y_axis: string[]; explained: number | null;
  closest: string[]; toward: string | null; reason: string | null; notes: string[];
}

/** Two panels the API reads off a run's counted baseline answers (insights.py). `reason` says why one is empty. */
export interface Insights {
  sources: {
    answers: number; cited_answers: number; reason: string | null;
    sources: {
      domain: string; url: string; answers: number; buyer: number; brand: number; owned: boolean;
      kind: "owned" | "rival" | "review" | "community" | "media" | "other";
      /** On buyer answers: how many citing it mention the brand, the rivals named beside it, and which answers. */
      with_brand: number; rivals: { name: string; count: number }[]; probes: string[];
    }[];
    /** Sites cited beside rivals in buyer answers that never mention the brand, most-cited first. */
    rival_only: string[];
  };
  voice: {
    questions: number; brand: string; brand_recommended: number; reason: string | null;
    rivals: { name: string; count: number }[]; tied_top: number;
  };
  /** Absent from an API older than search capture. */
  searches?: Searches;
}

/** What the model searched for the buyer questions (insights.searches): near-duplicates grouped. */
export interface SearchTry { try_no: number; searches: string[]; pages: string[]; owned_pages: string[] }
export interface Searches {
  answers: number; searched_answers: number; runs: number; owned: number; reason: string | null;
  searches: { query: string; variants: string[]; answers: number; questions: string[]; pages: string[]; owned_pages: string[] }[];
  questions: Record<string, SearchTry[]>;
}

export interface RunSummary {
  id: string;
  created_at: string;
  scenario: string | null;
  status: string;
  company: string;
  alignment: number | null;
  claim_echo?: number | null;
  lens?: "claim" | "intent" | null;
  visibility: number | null;
  landed: number;
  lost: number;
  contested: number;
  unstated: number;
  imposed: number;
  unprioritised: number;
  /** Field name -> why that number is null. */
  na_reasons?: Record<string, string>;
}

/** Legend order: what is working, then each kind of gap, then the one that is not a gap. */
export const ZONES: Zone[] = ["landed", "lost_claim", "contested", "unstated_intent", "imposed", "unprioritised"];

export const OWNER_TITLE: Record<Owner, string> = {
  authority_gap: "Authority gap",
  messaging_gap: "Messaging gap",
  contested_identity: "Contested",
  imposed_identity: "Imposed identity",
  unprioritised_claim: "Unprioritised",
  none: "Aligned",
};

// Why each gap is whose problem. Mirrors drift.OWNER_TEXT, except messaging_gap: drift's "does not
// clearly say it either" reads as absolute beside a nonzero page count, so the web says it relatively.
export const OWNER_TEXT: Record<Owner, string> = {
  authority_gap: "You state this clearly and the models are not repeating it.",
  messaging_gap: "AI does not say it, and neither do enough of your own pages.",
  contested_identity: "AI talks about this and says the opposite of what you claim.",
  imposed_identity: "AI asserts this about you without you claiming it.",
  unprioritised_claim: "You say this on your own site and AI repeats it, but you did not mark it as "
    + "something you want to be known for.",
  none: "Intended positioning is reflected in AI answers.",
};

/**
 * The zones that are somebody's problem. `landed` is working and `unprioritised` is the company's
 * own claim being repeated back — neither belongs under a heading that calls it a gap. Mirrors
 * drift.GAP_ZONES; filtering on "not landed" silently made every new non-problem zone a gap.
 */
export const GAP_ZONES: Zone[] = ["contested", "lost_claim", "unstated_intent", "imposed"];

export const ZONE_ORDER: Record<Zone, number> = {
  contested: 0,   // AI contradicting a claim you care about outranks AI merely ignoring it
  lost_claim: 1,
  unstated_intent: 2,
  imposed: 3,
  unprioritised: 4,   // your own claim, echoed but unweighted: worth seeing, not a gap to fix
  landed: 5,
};

/** FastAPI puts the readable reason in `detail`; the bare status line is useless to a reader. */
async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, init);
  if (!r.ok) {
    const detail = await r.json().then((b) => b?.detail).catch(() => null);
    throw new Error(typeof detail === "string" ? detail : `${r.status} ${r.statusText} for ${path}`);
  }
  return r.json();
}

// ---------------------------------------------------------------- onboarding
export interface ClaimedAttribute {
  id: string;
  label: string;
  description: string | null;
  claim_quotes: string[];
  claim_pages: number;
  claim_pages_total: number;
  buyer_questions: string[];
  intended_weight: number | null;
  added_by_user: boolean;
  note: string | null;
}

/** How one extracted claim fared against the company's own pages. Mirrors schemas.ClaimCheck. */
export interface ClaimCheck {
  id: string;
  label: string;
  kept: boolean;
  quotes_matched: number;
  quotes_removed: number;
  not_found: boolean;
  notes: string[];
}

export interface CompanyDetail {
  id: string;
  created_at: string;
  profile: { name: string; domain: string; aliases: string[]; customer_types: string[];
             one_liner: string | null; warnings: string[]; logo_url?: string | null;
             /** What a buyer shops for; null on companies saved before categories existed. */
             core_category?: string | null; category_questions?: string[] };
  pages: string[];
  attributes: ClaimedAttribute[];
  warnings: string[];
  checks: ClaimCheck[];   // empty for companies saved before checks existed: their notes are in warnings
  replay: boolean;
  /** Null for companies onboarded before the audit existed. */
  audit: SiteAudit | null;
}

/** Could AI read the site, and where else it learns about the company. Mirrors schemas.SiteAudit. */
export type AuditStatus = "pass" | "fail" | "unknown";
export interface AuditCheck {
  key: "crawlers" | "raw_text" | "markup" | "headings" | "speed" | "llms_txt" | "no_js";
  status: AuditStatus;
  detail: string;
}
export interface SiteAudit {
  checked_at: string;
  site: AuditCheck[];
  claims: { attribute_id: string; label: string; page_url: string | null; checks: AuditCheck[];
            advice?: string[] }[];  // advice is absent on audits saved before it existed
  entities: { source: string; status: "found" | "missing" | "not_checked"; summary: string;
              says: string | null; url: string | null }[];
}

/** Checks again whether AI can read the site: plain fetches on the server, no model. */
export const reaudit = (id: string) => json<CompanyDetail>(`/api/companies/${id}/audit`, { method: "POST" });

export interface CompanySummary {
  id: string; name: string; domain: string; created_at: string;
  pages: number; attributes: number; intended: number;
}

export const getCompanies = () => json<CompanySummary[]>("/api/companies");

/** Removes a claim the customer typed. Extracted claims are evidence and cannot be deleted. */
export const deleteAttribute = (companyId: string, attributeId: string) =>
  json<CompanyDetail>(`/api/companies/${companyId}/attributes/${attributeId}`, { method: "DELETE" });
export const getCompany = (id: string) => json<CompanyDetail>(`/api/companies/${id}`);

/** The customer's own input: intent weights and claims their copy never makes. */
export const patchCompany = (
  id: string,
  body: { weights: Record<string, number>;
          added: { label: string; description: string | null; intended_weight: number }[];
          /** Omitted leaves it alone; "" clears it. */
          core_category?: string },
) => json<CompanyDetail>(`/api/companies/${id}`, {
  method: "PATCH",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface Health {
  ok: boolean;
  live_available: boolean;
  live_status: string;
  seed_company: string;
  /** The preloaded Profound tab: a committed live run, opened as a finished report. */
  showcase: { company: string; run: string };
  /** Hosted demo: saved replay only, onboarding and live runs are refused by the server. */
  public_demo: boolean;
  /** Where to ask for a personal live link, or for a pass's cap to be raised. */
  contact_email: string;
  /** The model that answers the questions, and the separate one that judges them; null without a key. */
  /** The models ACTUALLY in use: preflight drops to a fallback when OpenAI refuses the configured
   * pair, and `model_fallback` then says why in words safe to show. */
  measured_model: string | null;
  evaluator_model: string | null;
  configured_measured_model: string | null;
  /** Which search mode is in force, down to "none" when no model would take the tool. */
  search_mode: string | null;
  model_fallback: string | null;
  /** Every measured call is made with tool_choice forcing the web_search tool. */
  forced_search: boolean;
  /** Buyer questions per front, how many of them are re-asked, and how many times. */
  buyer_questions: number;
  repeat_sample: number;
  buyer_tries: number;
}

export const getHealth = () => json<Health>("/api/health");

/** An access pass on the hosted demo: live runs on the owner's key, up to a dollar cap. */
export interface PassStatus { label: string; spent_usd: number; cap_usd: number; capped: boolean }

/** Trades a personal link's code for an HttpOnly session cookie. Throws the server's plain message. */
export const exchangePass = (code: string) => json<{ pass: PassStatus }>("/api/access/exchange", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ code }),
});
/** The meter. `visit` records a page load in the owner's visit log. */
export const getPass = (visit = false) =>
  json<{ pass: PassStatus | null }>(`/api/access${visit ? "?visit=1" : ""}`);
export const getRuns = () => json<RunSummary[]>("/api/runs");
export const getRun = (id: string) => json<Run>(`/api/runs/${id}`);

/** Asks one buyer question again with the rewritten passage as a source: one metered model call. */
export const reaskRun = (id: string, probe_id: string) =>
  json<Run>(`/api/runs/${id}/reask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ probe_id }),
  });

/** Re-scores a finished run's saved answers with intent weights. No model is asked. */
export const rescoreRun = (id: string, weights: Record<string, number>) =>
  json<Run>(`/api/runs/${id}/rescore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weights }),
  });

/** One answer, the moment the model returns it. `answer` is the first few hundred characters. */
export interface StreamAnswer {
  probe_id: string; kind: "blind" | "named"; phase: string; topic_label: string | null;
  try_no?: number; text: string; status: string; answer: string; provenance: string; grounded: boolean | null;
  done: number; expected: number;
}

/** A graph node finished. `planned` counts every question the run has decided to ask so far. */
export interface StreamNode {
  node: string; stage: string; agent: string; log: string; mode: string;
  planned: { buyer: number; brand: number; followup: number };
  competitors: string[];
}

export interface StreamHandlers {
  onNode?: (e: StreamNode) => void;
  onAnswer?: (e: StreamAnswer) => void;
  onDone?: (e: { run_id: string; run: Run }) => void;
  onError?: (e: { message: string }) => void;
}

/**
 * Opens one SSE stream. `last` names the event after which the server ends the response; closing
 * there stops EventSource reconnecting and replaying the whole job.
 */
function openStream(
  path: string,
  handlers: Record<string, ((d: never) => void) | undefined>,
  last: string,
  onError?: (e: { message: string }) => void,
): () => void {
  const es = new EventSource(`${API}${path}`);
  for (const [name, fn] of Object.entries(handlers)) {
    es.addEventListener(name, (ev) => {
      fn?.(JSON.parse((ev as MessageEvent).data) as never);
      if (name === last) es.close();
    });
  }
  // One listener for both error shapes: the server's `event: error` carries JSON,
  // while a transport failure dispatches a bare Event with no data. Closing either
  // way stops EventSource from retrying forever.
  es.addEventListener("error", (ev) => {
    const data: unknown = (ev as MessageEvent).data;
    onError?.(
      typeof data === "string"
        ? (JSON.parse(data) as { message: string })
        : { message: `Could not reach the API at ${API}. Check the API server is running.` },
    );
    es.close();
  });
  return () => es.close();
}

/** Measures one onboarded company. The UI only ever asks for live; the server owns any fallback. */
export const streamRun = (companyId: string, h: StreamHandlers) =>
  openStream(`/api/stream?company=${encodeURIComponent(companyId)}&mode=live`,
             { node: h.onNode, answer: h.onAnswer, done: h.onDone }, "done", h.onError);

/** Onboarding as it happens: the crawl's page list first, then the saved company. */
export const streamOnboard = (url: string, name: string, h: {
  onPages?: (e: { pages: string[] }) => void;
  onCompany?: (c: CompanyDetail) => void;
  onError?: (e: { message: string }) => void;
}) => openStream(`/api/onboard/stream?url=${encodeURIComponent(url)}&name=${encodeURIComponent(name)}`,
                 { pages: h.onPages, company: h.onCompany }, "company", h.onError);
