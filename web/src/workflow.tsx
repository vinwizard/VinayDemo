// One company, start to finish, on one screen: read their site, extract what it claims, choose what
// matters, ask AI, score. The preloaded Notion tab and "Onboard your own company" are this same
// component; the only difference is whether the company already exists when it mounts.
//
// Every stage's state is derived from events the server actually sent — the crawl's page list, the
// saved company, the graph's node events and one event per answer. Nothing here runs on a timer.
import { Children, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { CompanyDetail, CompanySummary, Run, StreamAnswer, StreamNode } from "./api";
import { getCompanies, getCompany, streamOnboard, streamRun } from "./api";
import { ClaimsStep } from "./claims";
import { Logo, Report } from "./components";
import { PROVENANCE_LABEL, day, headline, plain, potentialText, streamingProbeLabel } from "./labels";

type StageState = "pending" | "active" | "done" | "skipped" | "failed";

function Stage({ n, title, state, summary, children, last }: {
  n: number; title: string; state: StageState; summary?: ReactNode; children?: ReactNode;
  last?: boolean;
}) {
  // Open while it is the thing happening; a finished stage folds to its one-line summary and the
  // reader can unfold it. The override resets when the stage changes state.
  const [override, setOverride] = useState<{ state: StageState; open: boolean } | null>(null);
  const auto = state === "active" || state === "failed";
  const hasBody = Children.toArray(children).length > 0;   // drops the false of a {cond && …}
  const open = hasBody && (override?.state === state ? override.open : auto);
  const mark = state === "done" ? "✓" : state === "failed" ? "!" : state === "skipped" ? "–" : n;
  return (
    <section className={`stage ${state}${last ? " last" : ""}`} aria-label={title}>
      <div className="stage-mark" aria-hidden>{mark}</div>
      <div className="stage-main">
        <button className="stage-head" aria-expanded={hasBody ? open : undefined} disabled={!hasBody}
                onClick={() => setOverride({ state, open: !open })}>
          <span className="stage-title">{title}</span>
          <span className="stage-summary">{summary}</span>
          {hasBody && <span className="chev" aria-hidden>{open ? "▾" : "▸"}</span>}
        </button>
        {open && <div className="stage-body">{children}</div>}
      </div>
    </section>
  );
}

const host = (url: string) => {
  try { return new URL(url.includes("://") ? url : `https://${url}`).host; } catch { return url; }
};
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

interface Progress {
  node: StreamNode | null;      // latest node event: planned counts, discovered competitors, mode
  nodes: string[];
  answers: StreamAnswer[];
  run: Run | null;
  error: string | null;
}
const NO_PROGRESS: Progress = { node: null, nodes: [], answers: [], run: null, error: null };

/** The answers of one stage, in the order they arrived, each with the question that produced it. */
function AnswerList({ answers, replay }: { answers: StreamAnswer[]; replay: boolean }) {
  // Capped in height so every stage stays on screen; follow the newest answer as it lands.
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" }); }, [answers.length]);
  if (!answers.length) return <p className="muted" style={{ margin: 0 }}>Waiting for the first answer…</p>;
  return (
    <ol className="answers" ref={list}>
      {answers.map((a) => (
        <li key={`${a.probe_id}#${a.try_no ?? 1}`} className={a.status === "ok" ? "" : "bad"}>
          <div className="answer-q">
            <span className="muted" title={a.probe_id}>
              {streamingProbeLabel(a.probe_id, a.kind, a.phase, a.topic_label)}
              {(a.try_no ?? 1) > 1 && ` · try ${a.try_no}`}
            </span>
            <span>{a.text}</span>
          </div>
          <div className="answer-a">
            {a.status !== "ok"
              ? <span className="warn">No answer ({a.status}) — excluded from the scores.</span>
              : <>
                  {replay && <span className="tag sample">sample</span>}
                  {!replay && a.grounded === false
                    && <span className="tag warn">no web search — excluded from scores</span>}
                  {plain(a.answer)}{a.answer.length >= 320 && "…"}
                </>}
          </div>
        </li>
      ))}
    </ol>
  );
}

const PageList = ({ pages }: { pages: string[] }) => (
  <ul className="pages">
    {pages.map((u) => <li key={u}><a href={u} target="_blank" rel="noreferrer">{u.replace(/^https?:\/\//, "")}</a></li>)}
  </ul>
);

type Onboarding = { phase: "idle" | "reading" | "extracting" | "failed"; pages: string[]; error?: string };

export function CompanyWorkflow({ companyId, preloaded, publicDemo, onRunSaved }: {
  companyId?: string;           // preloaded: the company already exists and stages 1–2 are done
  preloaded?: boolean;
  publicDemo?: boolean;         // replays are not saved, so there is nothing to re-score
  onRunSaved: () => void;
}) {
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [onb, setOnb] = useState<Onboarding>({ phase: "idle", pages: [] });
  const [known, setKnown] = useState<CompanySummary[]>([]);
  const [running, setRunning] = useState(false);
  const [p, setP] = useState<Progress>(NO_PROGRESS);
  const closer = useRef<(() => void) | null>(null);
  const reportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (companyId) getCompany(companyId).then(setCompany).catch((e: Error) => setLoadError(e.message));
    else getCompanies().then(setKnown).catch(() => {});
    return () => closer.current?.(); // abort an in-flight stream if the tab unmounts
  }, [companyId]);

  const read = () => {
    setOnb({ phase: "reading", pages: [] }); setCompany(null); setP(NO_PROGRESS);
    closer.current?.();
    closer.current = streamOnboard(url, name, {
      onPages: (e) => setOnb({ phase: "extracting", pages: e.pages }),
      onCompany: (c) => { setCompany(c); setOnb((o) => ({ ...o, phase: "idle" })); },
      onError: (e) => setOnb((o) => ({ ...o, phase: "failed", error: e.message })),
    });
  };

  const reopen = (id: string) => {
    getCompany(id).then((c) => { setCompany(c); setOnb({ phase: "idle", pages: c.pages }); setP(NO_PROGRESS); })
      .catch((e: Error) => setOnb({ phase: "failed", pages: [], error: e.message }));
  };

  const startOver = () => {
    closer.current?.();
    setCompany(null); setP(NO_PROGRESS); setRunning(false); setOnb({ phase: "idle", pages: [] });
    getCompanies().then(setKnown).catch(() => {});
  };

  const measure = (c: CompanyDetail) => {
    setRunning(true); setP(NO_PROGRESS);
    closer.current?.();
    closer.current = streamRun(c.id, {
      onNode: (e) => setP((x) => ({ ...x, node: e, nodes: [...x.nodes, e.node] })),
      onAnswer: (e) => setP((x) => ({ ...x, answers: [...x.answers, e] })),
      onDone: (e) => {
        setP((x) => ({ ...x, run: e.run })); setRunning(false); onRunSaved();
        requestAnimationFrame(() => reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
      },
      onError: (e) => { setP((x) => ({ ...x, error: e.message })); setRunning(false); },
    });
  };

  if (loadError) return <div className="callout error">{loadError}</div>;
  if (companyId && !company) return <p className="muted">Loading…</p>;

  // ---------------------------------------------------------------- stages 1–2: onboarding
  const reading = onb.phase === "reading";
  const extracting = onb.phase === "extracting";
  const failedAt = onb.phase === "failed" ? (onb.pages.length ? 2 : 1) : 0;
  const pages = company?.pages ?? onb.pages;
  const domain = company?.profile.domain ?? host(url);
  const s1: StageState = company || onb.pages.length ? "done" : failedAt === 1 ? "failed" : "active";
  const s2: StageState = company ? "done" : failedAt === 2 ? "failed" : extracting ? "active" : "pending";

  // ---------------------------------------------------------------- stages 4–7: the run
  const started = running || p.run || p.error || p.answers.length > 0;
  const replay = !!company?.replay || p.node?.mode === "demo_replay" || p.run?.mode === "demo_replay";
  const planned = p.node?.planned;
  const of = (pred: (a: StreamAnswer) => boolean) => p.answers.filter(pred);
  // every ask of every buyer question, plus a control question per front: planned.buyer counts them all
  const buyer = of((a) => a.phase !== "followup" && a.kind === "blind");
  const brand = of((a) => a.phase === "baseline" && a.kind === "named");
  const follow = of((a) => a.phase === "followup");
  const decided = p.nodes.includes("choose_followup");
  const finished = (s: StageState) => s === "done" || s === "skipped";
  const tally = (got: number, want: number | undefined, go: boolean): StageState =>
    !started || want == null ? "pending" : want === 0 ? "skipped" : got >= want ? "done"
      : got > 0 || go ? "active" : "pending";
  // Brand questions go first: the buyer questions are planned from what their answers say.
  let s4: StageState = started && !planned ? "active" : tally(brand.length, planned?.brand, true);
  let s5: StageState = p.nodes.includes("plan_buyer") ? tally(buyer.length, planned?.buyer, true)
    : started && finished(s4) ? "active" : "pending";
  let s6: StageState = decided ? tally(follow.length, planned?.followup, true)
    : started && finished(s4) && finished(s5) ? "active" : "pending";
  let s7: StageState = p.run ? "done" : started && finished(s6) ? "active" : "pending";
  if (p.error) {
    // the stage that was running when it broke carries the failure; a setup failure is the first
    const firstOpen = [s4, s5, s6, s7].findIndex((s) => !finished(s));
    const at = firstOpen === -1 ? 3 : firstOpen;
    [s4, s5, s6, s7] = [s4, s5, s6, s7].map((s, i) => (i === at ? "failed" : s === "active" ? "pending" : s)) as
      [StageState, StageState, StageState, StageState];
  }
  const errorAt = (s: StageState) => s === "failed" && (
    <div className="callout error">
      {p.error}{" "}
      {company && <button className="linky" onClick={() => measure(company)}>Try again</button>}
    </div>
  );
  const brandName = company?.profile.name ?? (name || "the company");
  const weighted = company?.attributes.filter((a) => (a.intended_weight ?? 0) > 0) ?? [];
  const excluded = (xs: StreamAnswer[]) => xs.filter((a) => a.status !== "ok" || (!replay && a.grounded === false)).length;
  const answeredSummary = (xs: StreamAnswer[], want: number | undefined, noun: string) =>
    want == null ? undefined
      : !xs.length ? `${plural(want, noun)} queued`
      : `${xs.length} of ${plural(want, noun)} answered${excluded(xs) ? ` · ${excluded(xs)} excluded` : ""}`;

  return (
    <div className="workflow">
      {company && (
        <header className="company">
          <div className="row" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <Logo name={company.profile.name} url={company.profile.logo_url} size={36} />
            <h2>{company.profile.name}</h2>
            <a href={`https://${company.profile.domain}`} target="_blank" rel="noreferrer">{company.profile.domain}</a>
            {preloaded && <span className="tag preset">Preloaded example</span>}
            {!preloaded && (
              <button className="linky" style={{ marginLeft: "auto" }} onClick={startOver} disabled={running}>
                Onboard a different company
              </button>
            )}
          </div>
          {company.profile.one_liner && (
            <p className="one-liner">“{company.profile.one_liner}” <span className="muted">— how their own site puts it</span></p>
          )}
          {preloaded && !company.replay && (
            <p className="muted" style={{ margin: ".3rem 0 0" }}>
              The claims below come from a real read of {company.profile.domain} on {day(company.created_at)}.
              The intent weights are an example set for this demo, not {company.profile.name}’s own — move them.
            </p>
          )}
        </header>
      )}

      {replay && (
        <div className="callout sample">
          <strong>Offline replay — sample answers, not a measurement.</strong> The claims and the answers
          in every step below come from the bundled Notion sample: authored fixtures, not a read of the
          site. No model is being asked, and model judgment is simulated.
        </div>
      )}

      <Stage n={1} title="Read their site" state={s1}
             summary={company?.replay ? "No site was read — bundled sample data"
               : s1 === "done" ? `${plural(pages.length, "page")} read from ${domain}`
               : reading ? `Reading ${host(url)}…` : undefined}>
        {s1 === "done" ? (
          <PageList pages={pages} />
        ) : (
          <div className="stack">
            <p className="lede">
              Give a company name and its website. We read the homepage and up to five of its own
              product pages, and keep a claim only when a verbatim quote on one of those pages states it.
            </p>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <input aria-label="Company name" placeholder="Company name" value={name}
                     onChange={(e) => setName(e.target.value)} disabled={reading} />
              <input aria-label="Website" placeholder="https://example.com" value={url} style={{ flex: "1 1 16rem" }}
                     onChange={(e) => setUrl(e.target.value)} disabled={reading}
                     onKeyDown={(e) => { if (e.key === "Enter" && url.trim() && !reading) read(); }} />
              <button className="primary" onClick={read} disabled={reading || !url.trim()}>
                {reading ? "Reading…" : "Read their site"}
              </button>
            </div>
            {reading && <p className="muted working">Fetching {host(url)} and the product pages it links to…</p>}
            {failedAt === 1 && <div className="callout error">{onb.error}</div>}
            {known.length > 0 && !reading && (
              <p className="muted" style={{ margin: 0 }}>
                Or reopen one you already onboarded:{" "}
                {known.map((c, i) => (
                  <span key={c.id}>
                    {i > 0 && " · "}
                    <button className="linky" onClick={() => reopen(c.id)}>{c.name}</button>
                    {" "}({plural(c.pages, "page")}, {c.intended} weighted)
                  </span>
                ))}
              </p>
            )}
          </div>
        )}
      </Stage>

      <Stage n={2} title="Extract what they claim" state={s2}
             summary={company?.replay ? `${plural(company.attributes.length, "claim")} — authored sample claims`
               : company ? `${plural(company.attributes.length, "claim")} kept, each backed by a verbatim quote`
               : extracting ? "Reading the pages for claims…" : undefined}>
        {extracting && (
          <div className="stack">
            <p className="muted working" style={{ margin: 0 }}>
              An AI model is pulling out what these {plural(onb.pages.length, "page")} claim. Every claim
              must come with a quote that appears word for word on one of them, or it is dropped.
            </p>
            <PageList pages={onb.pages} />
          </div>
        )}
        {failedAt === 2 && <div className="callout error">{onb.error}</div>}
      </Stage>

      <Stage n={3} title="Choose what you want to be known for"
             state={!company ? "pending" : started ? "done" : "active"}
             summary={company && started ? `${plural(weighted.length, "claim")} weighted`
               : company ? "Your input — the one step nobody can derive from your site" : undefined}>
        {company && (
          <ClaimsStep key={company.id} company={company} running={running}
                      onCompany={setCompany} onMeasure={measure} />
        )}
      </Stage>


      <Stage n={4} title="Ask brand questions" state={s4}
             summary={s4 === "skipped" ? "Skipped — no brand question survived vetting"
               : answeredSummary(brand, planned?.brand, "question")
                 ?? `Questions that name ${brandName} but never name a claim`}>
        {s4 !== "pending" && s4 !== "skipped" && (
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>
              Each names {brandName} and none names a claim, so whatever AI says {brandName} is
              known for, it said unprompted.
            </p>
            {(s4 !== "failed" || brand.length > 0) && <AnswerList answers={brand} replay={replay} />}
            {errorAt(s4)}
          </div>
        )}
      </Stage>
      <Stage n={5} title="Ask buyer questions" state={s5}
             summary={s5 === "skipped" ? "Skipped — no weighted claim has a buyer question"
               : answeredSummary(buyer, planned?.buyer, "question")
                 ?? `Questions a buyer would ask without naming ${brandName}`}>
        {s5 !== "pending" && s5 !== "skipped" && (
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>
              Each one is what a buyer would type with no brand named, on two fronts: the category
              the brand answers place {brandName} in, and the one its own site aims for. Does AI bring {brandName} up on its own?
              {!replay && " Each is asked more than once, because the same question gets a different"
                + " answer each time; the control question asks for the category's leading tools."}
            </p>
            {(s5 !== "failed" || buyer.length > 0) && <AnswerList answers={buyer} replay={replay} />}
            {errorAt(s5)}
          </div>
        )}
      </Stage>


      <Stage n={6} title="Follow up on products AI named" state={s6}
             summary={s6 === "skipped"
               ? (p.node?.competitors.length ? "Skipped" : "Skipped — no buyer answer named another product")
               : decided ? `${plural(planned?.followup ?? 0, "follow-up question")}${
                   p.node?.competitors.length ? ` · AI named ${p.node.competitors.join(", ")}` : ""}`
               : "If a buyer answer names other products, ask AI to compare them"}>
        {decided && (s6 === "active" || s6 === "done") && (
          <div className="stack">
            {p.node?.competitors.length ? (
              <p className="muted" style={{ margin: 0 }}>
                {replay ? "Named in the sample buyer answers:" : "Named in the buyer answers:"}{" "}
                <strong>{p.node.competitors.join(", ")}</strong>.
                {!replay && ` So we asked it to compare them with ${brandName}. Exploratory — not counted in alignment.`}
              </p>
            ) : null}
            <AnswerList answers={follow} replay={replay} />
          </div>
        )}
        {errorAt(s6)}
      </Stage>

      <Stage n={7} title="Score" state={s7} last
             summary={p.run?.drift
               ? `${headline(p.run.drift).label} · ${potentialText(headline(p.run.drift))}`
                 + ` · ${PROVENANCE_LABEL[p.run.mode] ?? p.run.mode}`
               : s7 === "active" ? "Checking every quote is verbatim, then placing each claim…"
               : "Every quote checked word for word against its answer, then each claim placed"}>
        {s7 === "active" && (
          <p className="muted working" style={{ margin: 0 }}>
            An answer only counts for a claim when the quote behind it appears word for word in that
            answer. Unverifiable observations are dropped, never repaired.
          </p>
        )}
        {errorAt(s7)}
      </Stage>

      {p.run && (
        <div ref={reportRef} className="report-wrap">
          <Report run={p.run} onRescored={(r) => { setP((x) => ({ ...x, run: r })); onRunSaved(); }}
                  weightNote={publicDemo ? "Weighting is available on the saved example reports in History." : undefined} />
        </div>
      )}
    </div>
  );
}
