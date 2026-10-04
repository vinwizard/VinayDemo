import { useState } from "react";
import type { ReactNode } from "react";
import type { Probe, RetrievalRow, Run, ScoredPassage } from "../api";
import { reaskRun } from "../api";
import { MATCH_STEP, checkProblems, missedQuestions, moved } from "../quickwins";
import { address, plural } from "../labels";
import { GLOSSARY } from "../glossary";
import { Popover, Term } from "../popover";
import { refs, quoted, searcher, tryStory, answeredOk, cited, score, behind } from "./util";
import { Section, SAMPLE_NOTE, Tile } from "./ui";
import { QRef } from "./questions";

type Why = "searches" | "fixes" | "site";

/**
 * "Why AI misses you" in three numbers, each opening its table on the Evidence page: the AI's
 * searches, the match test and the site check. What each rests on is one hover away.
 */
export function WhyNumbers({ run, onOpen }: { run: Run; onOpen: (to: Why) => void }) {
  const s = run.insights?.searches;
  const sim = run.retrieval;
  const brand = run.profile.name;
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  const recorded = s && !s.reason ? buyer.filter((p) => s.questions[p.id]?.length) : [];
  const missed = s ? missedQuestions(s.questions, recorded.map((p) => p.id)) : [];
  const placed = new Set(buyerGroups(run)[0]?.probes.map((p) => p.id));
  const compared = sim?.rows.filter((r) => r.yours && r.rival) ?? [];
  const withFix = sim?.rows.filter((r) => r.fixed && r.yours) ?? [];
  const up = withFix.filter((r) => moved(r.yours!.score, r.fixed!.score) >= MATCH_STEP).length;
  const down = withFix.filter((r) => moved(r.yours!.score, r.fixed!.score) <= -MATCH_STEP).length;
  const checks = run.audit?.claims.length ? checkProblems(run.audit.claims) : null;
  const facts = (source: string) => run.audit?.entities.find((e) => e.source === source)?.status;
  const cell = (to: Why, big: string, text: string) => (
    <button type="button" className="why-num" onClick={() => onOpen(to)}><b>{big}</b><span>{text}</span></button>
  );
  if (!recorded.length && !compared.length && !checks) return null;
  return (
    <Tile wide sample={run.mode !== "live_api"} title={(
      <Popover wide label="Why AI misses you" className="term" trigger="Why AI misses you">
        <strong className="pop-title">Why AI misses you</strong>
        {recorded.length > 0 && (
          <p>{searcher(run)} ran {plural(s!.searches.length, "search", "searches")}; {s!.owned} ended in an answer that cited your site.
            {placed.size > 0 && [...placed].every((id) => missed.includes(id))
              && ` None of the ${placed.size} “where AI places you” questions did.`}</p>
        )}
        {compared.length > 0 && (
          <p>Your best page matches the question less closely than the page AI cited.
            {withFix.length > 0 && ` The suggested rewrites score higher on ${up} of the ${withFix.length} questions they target, lower on ${down}.`}</p>
        )}
        {checks && (
          <p>{checks.failing.length ? checks.failing.slice(0, 2).map((f) => `${GLOSSARY[f.key].term} fails on ${f.n}`).join("; ") + "." : "Nothing fails."}
            {facts("Wikidata") === "found" && facts("Wikipedia") === "found" ? ` Wikipedia and Wikidata know ${brand}.`
              : facts("Wikidata") === "missing" ? " No Wikidata entry." : ""}</p>
        )}
        <p className="muted">Each number opens its table on the Evidence page.</p>
      </Popover>
    )}>
      <div className="why-nums">
        {recorded.length > 0 && cell("searches", `${missed.length} of ${recorded.length}`, `buyer questions: no page AI cited was ${brand}'s`)}
        {compared.length > 0 && cell("fixes", `${compared.filter(behind).length} of ${compared.length}`, "your best page loses the match to the page AI cited")}
        {checks && cell("site", `${checks.pages} of ${run.audit!.claims.length}`, "claim pages have something in AI's way")}
      </div>
    </Tile>
  );
}

/** The buyer questions in the three groups the report uses: where AI places you, where you aim to
 * be, and the questions asked for your own claims. */
function buyerGroups(run: Run): { title: ReactNode; probes: Probe[] }[] {
  const topics = new Map(run.topics.map((t) => [t.id, t]));
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  const front = (p: Probe) => topics.get(p.topic_id)?.front ?? null;
  const label = (f: string) => topics.get(buyer.find((p) => front(p) === f)?.topic_id ?? "")?.label ?? "";
  const groups: { title: ReactNode; probes: Probe[] }[] = [];
  const placed = buyer.filter((p) => front(p) === "placed" || front(p) === "both");
  const aiming = buyer.filter((p) => front(p) === "aiming");
  if (placed.length) groups.push({ title: <><Term k="where_placed">Where AI places you</Term>: {label(front(placed[0])!)}</>, probes: placed });
  if (aiming.length) groups.push({ title: <><Term k="where_aiming">Where you aim to be</Term>: {label("aiming")}</>, probes: aiming });
  const rest = buyer.filter((p) => !placed.includes(p) && !aiming.includes(p));
  if (rest.length) groups.push({ title: "Your claims", probes: rest });
  return groups;
}

/**
 * The model's own web searches for the buyer questions, grouped by the question they came from: does
 * any answer to it cite a page of yours? One question opens to its searches; the flat list of every
 * search, near-duplicates grouped, is one click away.
 */
export function WhatItSearched({ run }: { run: Run }) {
  const [flat, setFlat] = useState(false);
  const s = run.insights?.searches;
  if (!s) return null;
  const replay = run.mode !== "live_api";
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  // The story: a question whose answer cited pages, none of them yours, preferring one that did not
  // name you either; else the first with searches.
  const first = (p: Probe) => s.questions[p.id]?.[0];
  const missed = buyer.filter((p) => first(p)?.pages.length && !first(p)!.owned_pages.length);
  const story = missed.find((p) => run.evaluations.find((e) => e.probe_id === p.id)?.mentioned === false)
    ?? missed[0] ?? buyer.find((p) => first(p)?.searches.length);
  const found = s.reason ? (s.answers ? "no web searches" : buyer.some((p) => answeredOk(run, p)) ? "not recorded" : "no buyer answers") : `${searcher(run)} ran ${plural(s.searches.length, "different search", "different searches")};`
    + ` your site was cited after ${s.owned ? s.owned : "none"} of them`;
  return (
    <Section title="What the AI searched" found={found}>
      {s.reason ? <p className="muted" style={{ margin: 0 }}>{s.reason}</p> : (
        <>
          <p style={{ margin: 0 }}>
            {replay && <>{SAMPLE_NOTE} The searches were written by hand too. </>}
            To answer a buyer, the AI first runs a few <Term k="fan_out">web searches</Term> of its own.
            A search that never leads to your site is where you go missing. Open a question for its searches.
          </p>
          {story && (
            <p className="callout story-line">
              {replay && <span className="tag sample">sample</span>}
              When a buyer asked “{story.text}”, {tryStory(first(story)!, searcher(run))}
            </p>
          )}
          {!flat ? (
            <div className="table-scroll">
              <table className="compact">
                <thead><tr><th>Buyer question</th><th className="num">Searches</th><th>Cited your site?</th></tr></thead>
                {buyerGroups(run).map((g, gi) => (
                  <tbody key={gi}>
                    <tr className="grp"><td colSpan={3}>{g.title} · {g.probes.filter((p) => cited(s.questions[p.id]) === true).length} of {plural(g.probes.length, "question")} cited you</td></tr>
                    {g.probes.map((p) => {
                      const tries = s.questions[p.id] ?? [];
                      const searches = [...new Set(tries.flatMap((t) => t.searches))];
                      const pages = [...new Set(tries.flatMap((t) => t.pages))];
                      const yours = cited(tries);
                      return (
                        <tr key={p.id}>
                          <td>
                            <details className="qsearches">
                              <summary>{p.text}</summary>
                              <div className="chips">{searches.map((q) => <span key={q} className="chip-q">{q}</span>)}</div>
                              <p className="muted" style={{ margin: ".3rem 0 0" }}>
                                {plural(pages.length, "page")} cited{yours ? `, ${plural(new Set(tries.flatMap((t) => t.owned_pages)).size, "of them", "of them")} yours` : ", none yours"} · <QRef id={p.id} run={run} />
                              </p>
                            </details>
                          </td>
                          <td className="num">{searches.length}</td>
                          <td>{yours == null ? <span className="muted">not recorded</span> : yours ? <span className="ok">Yes</span> : "No"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                ))}
              </table>
            </div>
          ) : (
            <ul className="search-list">
              {s.searches.map((g) => (
                <li key={g.query}>
                  <Popover wide label={`Search: ${g.query}`} className="search-row"
                           trigger={<>
                             <span className="search-q">“{g.query}”</span>
                             <span className="chip-count">{plural(g.answers, "answer")}</span>
                             {g.owned_pages.length ? <span className="pill landed">your site</span>
                               : <span className="pill neutral">not you</span>}
                           </>}>
                    <strong className="pop-title">“{g.query}”</strong>
                    {g.variants.length > 0 && (
                      <p className="muted">Also searched as {quoted(g.variants)}: the same search with another year or spelling.</p>
                    )}
                    <h4>Came from</h4>
                    <p>{refs(g.questions, run)} · run in {plural(g.answers, "answer")}</p>
                    <h4>Pages cited in {g.answers === 1 ? "that answer" : "those answers"}</h4>
                    {g.pages.length ? (
                      <ul className="page-list">
                        {g.pages.map((u) => (
                          <li key={u}>{address(u)}{g.owned_pages.includes(u) && <> <span className="pill landed">your site</span></>}</li>
                        ))}
                      </ul>
                    ) : <p className="muted">None.</p>}
                    <p className="muted">
                      The AI does not say which search found which page, so this lists every page{" "}
                      {g.answers === 1 ? "that answer" : "those answers"} cited
                      {replay && ". Every example.com address is a fictional placeholder"}.
                    </p>
                  </Popover>
                </li>
              ))}
            </ul>
          )}
          <p style={{ margin: 0 }}>
            <button type="button" className="linky" onClick={() => setFlat((f) => !f)}>
              {flat ? "Group the searches by buyer question" : `Show all ${plural(s.searches.length, "search", "searches")} as one list`}
            </button>
          </p>
        </>
      )}
    </Section>
  );
}

/** A passage in place: its page, the words, and which search it matched best. */
function PassageQuote({ title, p }: { title: string; p: ScoredPassage }) {
  return (
    <>
      <h4>{title} · {score(p.score)}</h4>
      <p className="muted" style={{ margin: 0 }}>{address(p.url)} · closest to “{p.query}”</p>
      <p className="quote">{p.text}</p>
    </>
  );
}

/** Ask the model once more with the rewritten passage and the cited page as its only sources. */
function Reask({ run, r, got, onReasked }: {
  run: Run; r: RetrievalRow; got: RetrievalRow["reask"];
  onReasked: (probe: string, got: RetrievalRow["reask"]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (run.mode !== "live_api" || !r.fixed) return null;
  const ask = () => {
    setBusy(true); setError(null);
    reaskRun(run.id, r.probe_id)
      .then((next) => onReasked(r.probe_id, next.retrieval?.rows.find((x) => x.probe_id === r.probe_id)?.reask ?? null))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <div className="reask">
      {got ? (
        <p style={{ margin: 0 }}>
          <span className="tag sample">quick check, not proof</span>{" "}
          Handed the rewritten passage and the cited page as its only sources, {got.model}{" "}
          {got.named ? <strong className="own">named {run.profile.name}.</strong> : <strong>still did not name {run.profile.name}.</strong>}
        </p>
      ) : (
        <button type="button" className="primary" disabled={busy} onClick={ask}>
          {busy ? "Asking…" : "Quick check: 1 ask, not proof"}
        </button>
      )}
      <p className="muted" style={{ margin: 0 }}>
        {got ? "One ask, not a measurement: it changes no number." : "One model call on your pass. A simulation: the AI is handed both passages as its only sources, so it shows whether the rewrite would be used, not whether a real search finds it."}
      </p>
      {error && <div className="callout error">{error}</div>}
    </div>
  );
}

/** A retrieval row's result in words: how the rewrite moved your match, else how you compare. */
function fixResult(r: RetrievalRow): { text: string; tone: string } {
  if (r.fixed && r.yours) {
    const d = moved(r.yours.score, r.fixed.score);
    if (r.rival && r.fixed.score >= r.rival.score) return { text: "Rewrite matches as well as the cited page", tone: "ok" };
    return d >= MATCH_STEP ? { text: "Rewrite: closer", tone: "ok" } : d <= -MATCH_STEP ? { text: "Rewrite: worse", tone: "worse" }
      : { text: "Rewrite: no change", tone: "muted" };
  }
  if (!r.rival || !r.yours) return { text: "No cited page to compare", tone: "muted" };
  return behind(r) ? { text: "Cited page matches better", tone: "muted" } : { text: "You match better", tone: "ok" };
}

const SHOWN_FIX_ROWS = 8;

/**
 * Test a fix: per buyer question, your best passage against the best passage of a page AI cited,
 * and yours again with the win-back rewrite in the page. Similarity only, labelled as a simulation.
 * One table, rows with a suggested fix first; a question opens its passages and the quick check.
 */
export function TestAFix({ run, reasks, onReasked }: {
  run: Run; reasks: Record<string, RetrievalRow["reask"]>;
  onReasked: (probe: string, got: RetrievalRow["reask"]) => void;
}) {
  const [all, setAll] = useState(false);
  const sim = run.retrieval;
  if (!sim) return null;
  const replay = sim.provenance !== "live_api";
  const probes = new Map(run.probes.map((p) => [p.id, p]));
  const fixes = new Map((run.win_back ?? []).map((a) => [a.attribute_id, a]));
  const compared = sim.rows.filter((r) => r.yours && r.rival);
  const weaker = compared.filter(behind).length;
  const found = compared.length
    ? `Your best page is weaker than the page AI cited for ${weaker} of ${plural(compared.length, "unbranded question")}`
    : "no page AI cited could be compared";
  const rows = [...sim.rows].sort((a, b) => Number(!!b.fixed) - Number(!!a.fixed) || Number(behind(b)) - Number(behind(a)));
  const shown = all ? rows : rows.slice(0, SHOWN_FIX_ROWS);
  const num = (p: ScoredPassage | null) => (p ? score(p.score) : "–");
  return (
    <Section title="Test a fix" found={found}>
      <p style={{ margin: 0 }}>
        {replay && <>Authored sample, not computed: the passages and scores were written by hand to show this panel. </>}
        A <Term k="retrieval_score">retrieval score</Term> from 0 to 1: how closely a passage of a page matches the
        question and the AI's searches for it. We scored your pages, the pages AI cited, and your page with the
        suggested rewrite from Quick wins in it. A simulation of what the AI reads first, not a promise of a citation.
        Open a question for the passages.
      </p>
      <div className="table-scroll">
        <table className="compact">
          <thead><tr><th>Buyer question</th><th className="num">You</th><th className="num">Page AI cited</th>
            <th className="num">With the fix</th><th>Result</th></tr></thead>
          <tbody>
            {shown.map((r) => {
              const p = probes.get(r.probe_id);
              const fix = r.fix_attribute_id ? fixes.get(r.fix_attribute_id) : undefined;
              const res = fixResult(r);
              return (
                <tr key={r.probe_id}>
                  <td>
                    <Popover wide label={`Passages for: ${p?.text ?? r.probe_id}`} className="linky row-open" trigger={p?.text ?? r.probe_id}>
                      <strong className="pop-title">{p?.text}</strong>
                      {replay && <p><span className="tag sample">sample</span> Written by hand; example.com pages are fictional.</p>}
                      {r.yours ? <PassageQuote title="Your best passage" p={r.yours} /> : <p className="muted">None of your pages could be read.</p>}
                      {r.rival ? <PassageQuote title="Best passage of a page AI cited" p={r.rival} />
                        : <p className="muted">No page AI cited for this question could be read.</p>}
                      {r.fixed ? (
                        <>
                          <PassageQuote title={`With the fix${fix ? ` for “${fix.label}”` : ""}`} p={r.fixed} />
                          <p className="muted" style={{ margin: 0 }}>
                            {r.rival && r.fixed.score >= r.rival.score ? "The rewrite now matches this question at least as closely as the page AI cited."
                              : r.yours && r.fixed.score > r.yours.score ? "The rewrite closes part of the gap."
                              : "The rewrite does not match this question more closely than your page already does."}
                          </p>
                          <Reask run={run} r={r} got={r.reask ?? reasks[`${run.id}:${r.probe_id}`]} onReasked={onReasked} />
                        </>
                      ) : <p className="muted">No suggested fix targets this question.</p>}
                      <p className="muted">Scored against {plural(r.queries, "search", "searches")}: the question and the AI's own searches for it; the best match counts.</p>
                    </Popover>
                  </td>
                  <td className="num">{num(r.yours)}</td>
                  <td className="num">{num(r.rival)}</td>
                  <td className="num">{num(r.fixed)}</td>
                  <td className={res.tone}>{res.text}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > SHOWN_FIX_ROWS && (
        <p style={{ margin: 0 }}><button type="button" className="linky" onClick={() => setAll((x) => !x)}>
          {all ? "Show fewer" : `Show ${plural(rows.length - SHOWN_FIX_ROWS, "more question")}`}
        </button></p>
      )}
      {sim.skipped.length > 0 && (
        <details className="skipped">
          <summary className="muted">What we could not read ({sim.skipped.length})</summary>
          <ul>{sim.skipped.map((x, i) => <li key={i} className="muted">{x}</li>)}</ul>
        </details>
      )}
      {!replay && <p className="muted" style={{ margin: 0 }}>{plural(sim.passages, "passage")} from {plural(sim.pages, "page")}, scored with {sim.model}.</p>}
    </Section>
  );
}
