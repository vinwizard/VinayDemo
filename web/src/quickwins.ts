// The arithmetic behind Quick wins and the claims step, kept apart from the components so `node --test`
// runs it: what a rewrite changes on the page, how its match scores moved, and the words a slider shows.
// Structural types only: this file must not import api.ts, whose Vite globals the node tests cannot load.
interface Scored { score: number }
interface RetrievalRow { probe_id: string; yours: Scored | null; rival: Scored | null; fixed: Scored | null; fix_attribute_id: string | null }
interface SearchTry { owned_pages: string[] }
interface WinBackAction { attribute_id: string; question_ids: string[] }

export type DiffPart = { op: "same" | "add" | "del"; text: string };

const key = (w: string) => w.toLowerCase().replace(/[’']/g, "'").replace(/^[^\w']+|[^\w']+$/g, "");

/** A word diff of the copy on the page and the rewrite, removed words then added ones at each change. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/\s+/).filter(Boolean), b = after.split(/\s+/).filter(Boolean);
  const ka = a.map(key), kb = b.map(key);
  // lcs[i][j]: the longest common run of a[i..] and b[j..]; a page sentence is short, so O(n·m) is fine
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = ka[i] === kb[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffPart[] = [];
  const push = (op: DiffPart["op"], text: string) => {
    const last = out.at(-1);
    if (last?.op === op) last.text += ` ${text}`; else out.push({ op, text });
  };
  let i = 0, j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && ka[i] === kb[j]) { push("same", b[j]); i++; j++; }
    else if (j < b.length && (i === a.length || lcs[i][j + 1] >= lcs[i + 1][j])) push("add", b[j++]);
    else push("del", a[i++]);
  }
  return out;
}

export const wordsIn = (parts: DiffPart[], op: DiffPart["op"]) =>
  parts.filter((p) => p.op === op).reduce((n, p) => n + p.text.split(" ").length, 0);

/** One buyer question a rewrite targets: its best passage today, the page AI cited, and with the rewrite. */
export interface MatchRow { probe_id: string; today: number | null; cited: number | null; fixed: number | null; change: number | null }

/** A move smaller than this either way is no change: embedding scores wobble in the second decimal. */
export const MATCH_STEP = 0.02;

/** How far a score moved, to the two decimals it is shown with (so a shown +0.02 is +0.02, not 0.0199…). */
export const moved = (from: number, to: number) => Math.round((to - from) * 100) / 100;

/** The retrieval rows of the questions a rewrite targets. A row whose best fix was another claim's
 * rewrite has no score for this one ("not scored"), never the other rewrite's score. */
export function matchRows(action: WinBackAction, rows: RetrievalRow[]): MatchRow[] {
  const by = new Map(rows.map((r) => [r.probe_id, r]));
  return action.question_ids.map((id) => {
    const r = by.get(id);
    const fixed = r?.fixed && r.fix_attribute_id === action.attribute_id ? r.fixed.score : null;
    const today = r?.yours?.score ?? null;
    return { probe_id: id, today, cited: r?.rival?.score ?? null, fixed,
             change: fixed != null && today != null ? moved(today, fixed) : null };
  });
}

export type MatchVerdict = "closer" | "worse" | "no_change" | "not_scored";

/** Step ① of the proof, over the rows: closer on more questions than worse, worse on more, or neither. */
export function matchVerdict(rows: MatchRow[]): { verdict: MatchVerdict; closer: number; worse: number; scored: number } {
  const scored = rows.filter((r) => r.change != null);
  const closer = scored.filter((r) => r.change! >= MATCH_STEP).length;
  const worse = scored.filter((r) => r.change! <= -MATCH_STEP).length;
  const verdict = !scored.length ? "not_scored" : worse > closer ? "worse" : closer > worse ? "closer" : "no_change";
  return { verdict, closer, worse, scored: scored.length };
}

/** An intent weight (0–1) in words, the same weight underneath. */
export function intentWord(w: number): string {
  return w <= 0 ? "Not a goal" : w < 0.5 ? "Nice to have" : w < 0.9 ? "Important" : "Top priority";
}

/** The buyer questions where no answer, on any try, cited a page of the company's. */
export function missedQuestions(questions: Record<string, SearchTry[]>, ids: string[]): string[] {
  return ids.filter((id) => questions[id]?.length && !questions[id].some((t) => t.owned_pages.length));
}

/** The site checks that fail across a run's claim pages, most first, and those every page passes:
 * what is in AI's way, said once instead of once per claim. */
export function checkProblems<K extends string>(claims: { checks: { key: K; status: string }[] }[]) {
  const keys = [...new Set(claims.flatMap((c) => c.checks.map((k) => k.key)))];
  const count = (key: K, status: string) => claims.filter((c) => c.checks.some((k) => k.key === key && k.status === status)).length;
  return {
    failing: keys.map((key) => ({ key, n: count(key, "fail") })).filter((x) => x.n > 0).sort((x, y) => y.n - x.n),
    passing: keys.filter((key) => count(key, "pass") === claims.length),
    pages: claims.filter((c) => c.checks.some((k) => k.status === "fail")).length,
  };
}
