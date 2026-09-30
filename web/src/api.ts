// Typed client for the Python engine's HTTP API. Mirrors schemas.py — keep in sync.
// VITE_API lets a second checkout run beside the first without fighting over port 8000.
import type { FleetEvent, Verification } from "./fleetlog.ts";

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
  /** What the answering model read, step by step; absent when not recorded. */
  trace?: ReadStep[] | null;
  /** Why scoring left this answer out (scoring.exclusion, set by the server), or null when it counts. */
  excluded?: Exclusion | null;
}

export type Exclusion = "snapshot" | "replay" | "failed" | "ungrounded" | "off_topic" | "unconfirmed" | "missing";

/** One thing the model read: a search snippet, an opened page's lines or a find-in-page hit. */
export interface ReadResult { url: string; title: string | null; text: string; crawled: string | null }
export interface ReadStep {
  kind: "search" | "open_page" | "find_in_page";
  queries: string[]; url: string | null; pattern: string | null; results: ReadResult[];
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
  /** The buyer question heading the new passage, verbatim; absent on runs from before headings. */
  heading?: string | null;
  /** The passage's body. */
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
  /** How sampler-lite spent the buyer questions; absent on replays and older runs. */
  sampler?: SamplerReport | null;
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
      /** For a rival's own site, whose it is (insights.domain_keys); absent on runs served before it existed. */
      rival?: string | null;
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
  /** "live_api" for a measured run; anything else is a replayed sample. */
  mode?: string;
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

// Why each gap is whose problem, said relatively: a messaging gap can sit beside a nonzero page count.
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

/** A JSON body sent with `method`; the reply read like any other. */
const send = <T,>(path: string, method: "POST" | "PATCH", body: unknown) =>
  json<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

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
  /** Why the customer should look at this claim (marketing language), or null. Flagged claims are measured. */
  review?: string | null;
  /** Set aside on review: kept on file, not measured. */
  set_aside?: boolean;
  /** Found in the answers by the discovery pass; present on a run's attributes, absent on a company's. */
  discovered?: boolean;
  /** Every quote is in an uploaded document and on no public page: a gap is a messaging gap. */
  private_only?: boolean;
  /** A quote is also in an uploaded document; claim_pages counts public pages only. */
  in_documents?: boolean;
}

/** One thing onboarding read. Mirrors api.main.source_payload. */
export interface Source {
  url: string | null;
  title: string | null;
  /** page_fetch: read from the site · search_copy: as a search engine saved it · uploaded_document */
  kind: string;
  /** A search copy's age as the search engine gave it: "3 days ago". */
  saved: string | null;
  private: boolean;
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
  /** What was read and how; absent on companies saved before it existed (their pages were all read directly). */
  sources?: Source[];
  /** Pages others wrote about the company: shown, never read for claims. */
  third_party?: { url: string; title: string | null }[];
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
          core_category?: string;
          /** A flagged claim reviewed: keep it (and restore one set aside), or set it aside. */
          review?: Record<string, "keep" | "set_aside"> },
) => send<CompanyDetail>(`/api/companies/${id}`, "PATCH", body);

export interface Health {
  ok: boolean;
  live_available: boolean;
  /** A key is set on the server; live_available can still be false on the public demo without a pass. */
  key_configured: boolean;
  live_status: string;
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
  /** The most one why investigation may spend. */
  why_budget_usd?: number;
  /** The investigation fleet: its purse, its lanes, and one re-check's cap. */
  fleet_budget_usd?: number;
  fleet_concurrency?: number;
  verify_budget_usd?: number;
  /** The committed live example in History; the first-visit story is told with its run. */
  showcase?: { company: string; run: string } | null;
}

export const getHealth = () => json<Health>("/api/health");

/** An access pass on the hosted demo: live runs on the owner's key, up to a dollar cap. */
export interface PassStatus { label: string; spent_usd: number; cap_usd: number; capped: boolean }

/** Trades a personal link's code for an HttpOnly session cookie. Throws the server's plain message. */
export const exchangePass = (code: string) => send<{ pass: PassStatus }>("/api/access/exchange", "POST", { code });
/** The meter. `visit` records a page load in the owner's visit log. */
export const getPass = (visit = false) =>
  json<{ pass: PassStatus | null }>(`/api/access${visit ? "?visit=1" : ""}`);
export const getRuns = () => json<RunSummary[]>("/api/runs");
export const getRun = (id: string) => json<Run>(`/api/runs/${id}`);

/** Asks one buyer question again with the rewritten passage as a source: one metered model call. */
export const reaskRun = (id: string, probe_id: string) =>
  send<Run>(`/api/runs/${id}/reask`, "POST", { probe_id });

/** Re-scores a finished run's saved answers with intent weights. No model is asked. */
export const rescoreRun = (id: string, weights: Record<string, number>) =>
  send<Run>(`/api/runs/${id}/rescore`, "POST", { weights });

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

/** Onboarding as it happens: what was read first, then the saved company. `docs` are uploaded
 *  document ids; `onlyDocs` reads them instead of the website. */
export const streamOnboard = (url: string, name: string, h: {
  onPages?: (e: { pages: string[]; sources: Source[] }) => void;
  onCompany?: (c: CompanyDetail) => void;
  onError?: (e: { message: string }) => void;
}, docs: string[] = [], onlyDocs = false) =>
  openStream(`/api/onboard/stream?url=${encodeURIComponent(url)}&name=${encodeURIComponent(name)}`
             + `&docs=${docs.map(encodeURIComponent).join(",")}${onlyDocs ? "&only_docs=true" : ""}`,
             { pages: h.onPages, company: h.onCompany }, "company", h.onError);

/** A company a name could mean, from one web search. `exact`: its name is the name searched for. */
export interface Candidate { name: string; domain: string; what: string; exact: boolean }
export interface Found { candidates: Candidate[]; exact: boolean }
export const findCompany = (name: string, hint?: string) =>
  json<Found>(`/api/onboard/find?name=${encodeURIComponent(name)}${hint ? `&hint=${encodeURIComponent(hint)}` : ""}`);

/** An uploaded document: only its text is kept, on the server, for this pass alone. */
export interface UploadedDoc { id: string; filename: string; chars: number }
export const uploadDocument = (body: Blob, filename: string) =>
  json<UploadedDoc>(`/api/onboard/documents?filename=${encodeURIComponent(filename)}`, { method: "POST", body });

/** One experiment on the recorded reading list (why.py). */
export interface WhyArm {
  id: string;
  kind: "base" | "drop_source" | "drop_passage" | "edit" | "inject";
  label: string; urls: string[]; text: string[]; hypothetical: boolean;
  k: number; n: number;
  /** The base it was compared with, when it was decided. */
  base_k: number; base_n: number;
  effect: number | null;
  /** 95% interval of the effect, corrected for every look and arm of the investigation. */
  interval: [number, number] | null;
  decided: "effect" | "no_effect" | "undecided" | "base";
  quotes: string[];
}
export interface WhyVerdict {
  kind: "caused_by" | "over_determined" | "prior_belief" | "not_in_reading" | "not_said" | "copy_fix"
    | "authority_fix" | "not_movable" | "copy_lowers" | "not_reproducible" | "undecided" | "budget" | "cancelled"
    | "ceiling";
  text: string; arm_id: string | null; fix: "copy" | "authority" | "none" | null;
}
/** Why AI says (or does not say) one claim to one branded question, and what changes it. */
export interface Investigation {
  id: string; run_id: string; created_at: string; company: string; question: string; probe_id: string | null;
  attribute_id: string; claim: string; term: string | null; model: string; judge: string;
  /** What counted as saying it: a claim's endorsements, any mention (a perception AI raised, a literal
   * term), or, for a quick win's replay test, whether the answer names the company, or recommends it
   * where the question already named it. */
  counts?: "mentions" | "endorsements" | "names" | "recommends";
  /** "buyer": a quick win's replay test on an unbranded question (why.test_rewrite). */
  kind?: "claim" | "buyer";
  /** A proven rewrite, re-checked live once published. */
  verification?: Verification | null;
  /** The investigation fleet that dispatched it, if one did. */
  fleet_id?: string | null;
  provenance: "counterfactual_replay"; budget_usd: number; spent_usd: number;
  status: "running" | "complete" | "stopped";
  live: { k: number; n: number }; off: { k: number; n: number }; live_quotes: string[];
  reading: ReadStep[]; arms: WhyArm[]; verdicts: WhyVerdict[]; log: string[];
}

export const getInvestigations = (runId: string) => json<Investigation[]>(`/api/runs/${runId}/why`);

/** One why investigation as it runs: its budget first, then log lines, experiments and verdicts. */
export const streamWhy = (runId: string, q: { attribute: string; probe?: string; question?: string; term?: string },
  h: {
    onStart?: (e: { budget_usd: number; question: string; model: string }) => void;
    onLog?: (e: { text: string; spent_usd: number }) => void;
    onArm?: (e: WhyArm) => void;
    onVerdict?: (e: WhyVerdict) => void;
    onDone?: (e: Investigation) => void;
    onError?: (e: { message: string }) => void;
  }) => {
  const params = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
  return openStream(`/api/runs/${runId}/why/stream?${params}`,
                    { start: h.onStart, log: h.onLog, arm: h.onArm, verdict: h.onVerdict, done: h.onDone },
                    "done", h.onError);
};

/** A quick win's replay test: its rewrite against one buyer question it was written for. */
export const streamRewriteTest = (runId: string, attribute: string, probe: string, h: {
    onStart?: (e: { budget_usd: number; question: string; model: string }) => void;
    onLog?: (e: { text: string; spent_usd: number }) => void;
    onDone?: (e: Investigation) => void;
    onError?: (e: { message: string }) => void;
  }) =>
  openStream(`/api/runs/${runId}/rewrite-test/stream?${new URLSearchParams({ attribute, probe })}`,
             { start: h.onStart, log: h.onLog, done: h.onDone }, "done", h.onError);

/** "Mark fix live" on a rewrite its replay test proved: the page first (free), then live asks. */
export const streamRecheck = (invId: string, h: {
    onLog?: (e: { text: string }) => void;
    onDone?: (e: Verification) => void;
    onError?: (e: { message: string }) => void;
  }) =>
  openStream(`/api/investigations/${invId}/verify/stream`, { log: h.onLog, done: h.onDone }, "done", h.onError);

// ---------------------------------------------------------------- the investigation fleet (fleet.py)
// Its records live in fleetlog.ts, which the node unit tests read without this file's Vite globals.
export type { Challenge, PlanItem, Verification } from "./fleetlog.ts";
export interface FleetSummary {
  id: string; run_id: string; created_at: string; status: "running" | "complete" | "stopped";
  spent_usd: number; wall_s: number | null; tasks: number; planned: boolean;
}
export interface FleetEstimate { candidates: number; picks: number; usd: number; minutes: number; budget_usd: number }

export const getFleets = (runId: string) =>
  json<{ fleets: FleetSummary[]; estimate: FleetEstimate | null }>(`/api/runs/${runId}/fleets`);
export const startFleet = (runId: string) => json<{ id: string }>(`/api/runs/${runId}/fleet`, { method: "POST" });

/** A fleet's log as it is written: every event after `after`, then `onEnd` once the fleet is done. */
export const streamFleet = (fleetId: string, after: number, onEvent: (e: FleetEvent) => void,
  onEnd: () => void, onError: (e: { message: string }) => void) =>
  openStream(`/api/fleets/${fleetId}/stream?after=${after}`, { fleet: onEvent, end: onEnd }, "end", onError);

/** Re-checks one fix of a finished fleet: the page first (free), then live asks. */
export const streamVerify = (fleetId: string, rank: number, onEvent: (e: FleetEvent) => void,
  onEnd: () => void, onError: (e: { message: string }) => void) =>
  openStream(`/api/fleets/${fleetId}/verify/stream?rank=${rank}`, { fleet: onEvent, end: onEnd }, "end", onError);

/** One front as sampler-lite asked it: fresh questions up to a stated margin at 95%. */
export interface FrontSample {
  front: Front; pool: number; asked: number; look: 1 | 2; stopped_early: boolean;
  named: number; judged: number; rate: number | null; interval: [number, number] | null;
  margin_met: boolean; note: string | null;
}
export interface SamplerReport {
  margin: number; looks: [number, number]; budget_usd: number | null; fronts: FrontSample[];
  wobble: string[]; decided: boolean; shared: number;
}
