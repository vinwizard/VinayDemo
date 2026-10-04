import type { ReactNode } from "react";
import type { Answer, AttributeScore, Demand, Probe, QueryEvaluation, Run } from "../api";
import { plain, probeLabels, plural } from "../labels";
import { GLOSSARY } from "../glossary";
import { Popover, Term } from "../popover";
import { WhatItRead } from "../why";
import { FrontMargin, SamplerNote } from "../margin";
import { na, frontsOf, gapSentence, leftOut, counts, questionKind, TABS, searcher, tryStory, answeredOk } from "./util";
import type { Vis } from "./util";
import { Section } from "./ui";
import { FrontLabel, Range, GapVerdict, Visibility } from "./figures";

/**
 * "Brand question 2" as something you can read in place: hover or tap shows the question, whether
 * it counted and why not, and the AI's answer — no trip to another tab. `text` shows the question
 * itself as the trigger instead of its short name.
 */
export function QRef({ id, run, text }: { id: string; run: Run; text?: boolean }) {
  const p = run.probes.find((x) => x.id === id);
  const name = probeLabels(run.probes, run.topics)[id] ?? id;
  if (!p) return <>{name}</>;
  const a = run.answers.find((x) => x.probe_id === id), e = run.evaluations.find((x) => x.probe_id === id);
  const why = p.phase === "baseline" ? leftOut(a, e, run.profile.name) : null;
  const tab = p.kind === "named" && p.phase === "followup" ? "sources" : "questions";
  return (
    <Popover wide label={name} className={text ? "qref qtext" : "qref"} trigger={text ? p.text : name}>
      <strong className="pop-title">{name}</strong>
      <p className="muted">{questionKind(p, run.profile.name)}</p>
      <p><strong>Asked:</strong> {p.text}</p>
      {why && <p className="warn">Left out of the scores: {why}.</p>}
      {p.kind === "blind" && p.phase === "baseline" && <Searched run={run} p={p} />}
      <h4>The AI’s answer</h4>
      <p className="muted long-answer">
        {a && run.mode !== "live_api" && <span className="tag sample">sample</span>}
        <Reused a={a} />
        {a ? plain(a.text) : "no answer"}
      </p>
      <a href={`#report-${tab}`}>Open in the {TABS.find(([t]) => t === tab)![1]} tab</a>
    </Popover>
  );
}

/** Question names and raw probe ids inside a server sentence, each made readable in place. */
export function Linked({ text, run }: { text: string; run: Run }) {
  const byName = new Map<string, string>();
  for (const [id, n] of Object.entries(probeLabels(run.probes, run.topics))) {
    byName.set(n, id);
    byName.set(n.replace(/ — .*/, ""), id);
    byName.set(id, id);
  }
  const keys = [...byName.keys()].sort((x, y) => y.length - x.length).map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!keys.length) return <>{text}</>;
  const parts = text.split(new RegExp(`\\b(${keys.join("|")})\\b`));
  return <>{parts.map((t, i) => (i % 2 ? <QRef key={i} id={byName.get(t)!} run={run} /> : t))}</>;
}


/** "real demand · Google": the question is a real search; the popover lists its group's phrasings. */
function DemandBadge({ d }: { d: Demand }) {
  const n = d.phrasings.length;
  return (
    // inside a <summary>: a tap on the badge opens the popover, not the answer
    <span className="demand" onClick={(e) => e.preventDefault()}>
      <Popover label="Real demand" className="demand-badge" trigger={<>real demand · Google</>}>
        <strong className="pop-title">{GLOSSARY.real_demand.term}</strong>
        <p>People search exactly this on Google.</p>
        {n > 1 && (
          <>
            <p className="muted">{n} real searches that mean the same, grouped together:</p>
            <ul className="demand-list">
              {d.phrasings.map((ph) => <li key={ph.text}>{ph.text}</li>)}
            </ul>
          </>
        )}
        <p className="muted">This shows the question is real, not how often it is searched.</p>
      </Popover>
    </span>
  );
}

/** What the model searched for one buyer question, every try, or that it was not recorded. */
function Searched({ run, p }: { run: Run; p: Probe }) {
  const s = run.insights?.searches;
  const tries = s?.questions[p.id];
  if (!s || p.phase !== "baseline" || (!tries && !answeredOk(run, p))) return null;
  return (
    <div className="searched">
      <h4>What the AI searched <Term k="fan_out" icon /></h4>
      {tries ? tries.map((t) => (
        <p key={t.try_no}>
          {run.mode !== "live_api" && <span className="tag sample">sample</span>}
          {tries.length > 1 && <strong>Try {t.try_no}: </strong>}{tryStory(t, searcher(run).replace(/^the/, "The"))}
        </p>
      )) : <p className="muted">Not recorded for this run.</p>}
    </div>
  );
}

/** An answer reused from an earlier run says so, and for which question when it was a near-identical one. */
function Reused({ a }: { a?: Answer }) {
  if (!a?.shared) return null;
  const when = a.collected_at ? new Date(a.collected_at).toLocaleString() : "an earlier run";
  return (
    <span className="tag">
      {a.reused_question && <>answered for a near-identical question: “{a.reused_question}” · </>}reused from {when}
    </span>
  );
}

/** One question as a compact row; opening it shows the full answer and what the scorer made of it. */
export function QuestionRow({ p, name, answer, verdict, tags, note, replay, after, sub }: {
  p: Probe; name: string; answer?: Answer; verdict?: ReactNode; tags?: ReactNode; note?: ReactNode;
  replay: boolean; after?: ReactNode; sub?: ReactNode;
}) {
  return (
    <details className="qrow">
      <summary>
        <span className="muted qrow-name" title={p.id}>{name}{sub && <> · {sub}</>}</span>
        <span className="qrow-text">{p.text}{p.demand && <DemandBadge d={p.demand} />}</span>
        {verdict}
      </summary>
      <div className="qrow-body">
        {tags && <div className="row" style={{ flexWrap: "wrap", gap: ".3rem" }}>{tags}</div>}
        {note}
        <p className="muted long-answer">
          {answer && replay && <span className="tag sample">sample</span>}
          <Reused a={answer} />
          {answer ? plain(answer.text) : "no answer"}
        </p>
        <WhatItRead a={answer} />
        {after}
      </div>
    </details>
  );
}

/** Buyer questions never name the company: did AI bring it up on its own? */
export function BuyerQuestions({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const d = run.drift;
  const brand = run.profile.name;
  const names = probeLabels(run.probes, run.topics);
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const evals = new Map(run.evaluations.map((e) => [e.probe_id, e]));
  const base = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline");
  const control = run.probes.find((p) => p.phase === "control");
  const realAsked = base.filter((p) => p.demand).length;
  const tries = d?.tries ?? 1;
  // Every try of one question, first try first: [answer, evaluation] pairs.
  const repeatAnswers = new Map((run.repeat_answers ?? []).map((a) => [`${a.probe_id}#${a.try_no}`, a]));
  const triesOf = (p: Probe) => [
    [answers.get(p.id), evals.get(p.id)] as const,
    ...(run.repeat_evaluations ?? []).filter((e) => e.probe_id === p.id)
      .sort((x, y) => (x.try_no ?? 1) - (y.try_no ?? 1))
      .map((e) => [repeatAnswers.get(`${p.id}#${e.try_no}`), e] as const),
  ];
  const countedTries = (p: Probe) => triesOf(p)
    .filter(([a, e]) => a && e && counts(a)).map(([, e]) => e!);
  const counted = (p: Probe) => {
    const a = answers.get(p.id), e = evals.get(p.id);
    return a && e && counts(a) ? e : null;
  };
  const all = base.flatMap(countedTries);
  const namedIn = all.filter((e) => e.mentioned).length;
  const recIn = all.filter((e) => e.recommended).length;
  // only the repeat-sampled questions have more than one try, so the total is asks, not questions x tries
  const asks = base.reduce((n, p) => n + triesOf(p).length, 0);
  const excluded = asks - all.length;
  const sampled = base.filter((p) => triesOf(p).length > 1).length;
  const verdict = (p: Probe) => {
    if (triesOf(p).length > 1) {
      const got = countedTries(p), k = got.filter((e) => e.mentioned).length;
      if (!got.length) return <span className="tag warn">excluded from scores</span>;
      const tone = k === 0 ? "lost_claim" : k === got.length ? "landed" : "unprioritised";
      return <span className={`pill ${tone}`}>named in {k} of {got.length} tries</span>;
    }
    const e = counted(p);
    if (!e) return <span className="tag warn">excluded from scores</span>;
    if (e.recommended) return <span className="pill landed">recommended you</span>;
    if (e.negative_mention) return <span className="pill contested">criticised you</span>;
    if (e.mentioned) return <span className="pill unprioritised">named you</span>;
    return <span className="pill lost_claim">did not name you yet</span>;
  };
  const tryWord = (a?: Answer, e?: QueryEvaluation) =>
    !a || !e || !counts(a) ? "excluded" : e.recommended ? "recommended you" : e.mentioned ? "named you" : "did not name you";
  // who AI named in the answer, on the card itself: the rival a buyer was shown instead
  const others = (p: Probe) => {
    const e = evals.get(p.id), named = e?.competitor_recommendations ?? [];
    return named.length ? `${e!.mentioned ? "also named" : "named instead"}: ${named.slice(0, 3).join(", ")}`
      + (named.length > 3 ? ` +${named.length - 3}` : "") : undefined;
  };
  const card = (p: Probe) => {
    const shown = triesOf(p);
    return (
      <QuestionRow key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)}
                   verdict={verdict(p)} replay={replay} sub={others(p)}
                   note={<>
                     {evals.get(p.id)?.explanation && <span className="muted">{evals.get(p.id)!.explanation}</span>}
                     <Searched run={run} p={p} />
                     {shown.length > 1 && (
                       <span className="muted">
                         {shown.map(([a, e], i) => `Try ${i + 1}: ${tryWord(a, e)}`).join(" · ")}. Every try’s answer is below.
                       </span>
                     )}
                   </>}
                   after={shown.slice(1).map(([a], i) => (
                     <p key={i} className="muted long-answer">
                       <strong>Try {i + 2}:</strong> {a ? plain(a.text) : "no answer"}
                     </p>
                   ))} />
    );
  };
  const vis = d?.visibility;
  // Grouped by front when the run has labelled ones; one unlabelled set otherwise, as replay has.
  const topicFront = new Map(run.topics.map((t) => [t.id, t.front ?? null]));
  const fronts = d ? frontsOf(d) : [];
  const probeById = new Map(run.probes.map((p) => [p.id, p]));
  return (
    <Section className="qset" title={<Term k="buyer_question">Unbranded questions</Term>}
               found={!base.length ? na(d?.na_reasons, "visibility")
                 : `${plural(base.length, "question")} asked once`
                   + (sampled ? `, ${sampled} of them ${tries} times over` : "")
                   + ` · named you in ${namedIn} of ${all.length} answers${recIn ? ` · recommended you in ${recIn}` : ""}`
                   + (excluded ? ` · ${excluded} excluded` : "")}>
        <details className="qhow">
        <summary>How these were asked ⓘ</summary>
        <p className="muted" style={{ margin: 0 }}>
          What a buyer would ask without naming {brand}. Each one AI answered without
          bringing {brand} up is room to be found.
          {fronts.length > 1 && ` They are asked on two fronts, half each: the category AI’s brand answers`
            + ` already place ${brand} in, and the category its own site aims for.`}
          {sampled > 0
            ? ` The model answers differently each time, so`
              + ` ${plural(sampled, "of these questions was", "of these questions were")} asked ${tries} times`
              + ` over in a fresh context, to show how much one question wobbles. Every question counts once`
              + ` towards the score however often it was asked: the budget goes on asking more different`
              + ` questions, which is what narrows the range.`
            : replay ? " A sample run replays one authored answer per question: 1 try." : " Each was asked once."}
        </p>
        <SamplerNote run={run} />
        {(realAsked > 0 || !!run.demand_notes?.length) && (
          <p style={{ margin: 0 }}>
            {realAsked ? `${realAsked} of ${base.length} are ` : "None of them are "}
            <Term k="real_demand" note={run.demand_notes?.join(" ")}>real searches</Term>
            {realAsked ? (realAsked < base.length ? "; AI wrote the rest." : ".") : ": AI wrote them all."}
          </p>
        )}
        {fronts.length > 0 && d && gapSentence(d, brand) && <p style={{ margin: 0 }}>{gapSentence(d, brand)}<GapVerdict d={d} /></p>}
        </details>
        {!fronts.length && vis != null && (
          <p style={{ margin: 0 }}>
            <strong>Buyer visibility <Visibility d={d!} explain /></strong>{" "}
            <span className="muted">— <Range d={d!} iv={d!.visibility_interval} note={d!.na_reasons?.visibility_interval} /></span>
          </p>
        )}
        {!fronts.length && d?.low_confidence && (
          <p className="warn" style={{ margin: 0 }}>{d.low_confidence} The control question is below the questions.</p>
        )}
        {!control && run.mode === "live_api" && !run.profile.core_category && (
          <p className="warn" style={{ margin: 0 }}>
            No <Term k="core_category">core category</Term> was saved for {brand}, so where it aims to be was not asked
            about. Set the category on the claims screen and measure again.
          </p>
        )}
        {fronts.length ? fronts.map((v) => {
          const ps = base.filter((p) => topicFront.get(p.topic_id) === v.front);
          const ctl = v.control_probe_id ? probeById.get(v.control_probe_id) : undefined;
          return (
            <div className="front-group" key={v.front}>
              <h4 style={{ margin: ".4rem 0 0" }}>
                <FrontLabel v={v} /> · {v.category} — <Visibility d={v} explain />{" "}
                <span className="muted">— <Range d={v} iv={v.interval} note={v.interval_note} /></span>
              </h4>
              {run.sampler && <p className="muted" style={{ margin: 0 }}><FrontMargin run={run} front={v.front} /></p>}
              <div className="qlist">{ps.map(card)}</div>
              {ctl && <Control run={run} p={ctl} v={v} />}
            </div>
          );
        }) : <div className="qlist">{base.map(card)}</div>}
        {fronts.length > 0 && base.some((p) => !topicFront.get(p.topic_id)) && (
          <div className="front-group">
            <h4 style={{ margin: ".4rem 0 0" }}>Your claims <span className="muted">— counted in neither front</span></h4>
            <div className="qlist">{base.filter((p) => !topicFront.get(p.topic_id)).map(card)}</div>
          </div>
        )}
      {!fronts.length && control && d && <Control run={run} p={control} v={d} />}
    </Section>
  );
}

/**
 * The control question of one set: can the answering model name the companies leading this category, and
 * does it count the brand among them? It is not a buyer question and never moves visibility; it only
 * says whether that set's number can be trusted.
 */
function Control({ run, p, v }: { run: Run; p: Probe; v: Vis }) {
  const a = run.answers.find((x) => x.probe_id === p.id);
  const e = run.evaluations.find((x) => x.probe_id === p.id);
  const flag = v.low_confidence;
  const ok = a && e && counts(a);
  const found = !ok ? "could not be scored"
    : `named ${plural(e.competitor_recommendations.length + (e.mentioned ? 1 : 0), "company", "companies")}`
      + ` · ${e.mentioned ? `including ${run.profile.name}` : `not ${run.profile.name}`}`;
  return (
    <Section title="Control question"
             found={flag ? <><Term k="low_confidence"><span className="tag warn">low confidence</span></Term> {found}</> : found}>
      <p className="muted" style={{ margin: 0 }}>
        One question asked beside the unbranded questions and never scored: does the answering model know
        who leads this category, and is {run.profile.name} among them? If not, this set’s buyer
        visibility is flagged low confidence.
      </p>
      {flag && <div className="callout warn-box" style={{ margin: 0 }}><strong>Low confidence.</strong> {flag}</div>}
      {!flag && ok && v.visibility === 0 && (
        <p style={{ margin: 0 }}>
          The model names {run.profile.name} among the companies leading this category, yet never brought it
          up for a buyer: the 0 is a finding, not a gap in what the model knows.
        </p>
      )}
      <div className="qlist">
        <QuestionRow p={p} name="Control question" answer={a} replay={run.mode !== "live_api"}
                     note={ok && e.competitor_recommendations.length > 0 && (
                       <span className="muted">Companies it named: {e.competitor_recommendations.join(", ")}</span>
                     )} />
      </div>
    </Section>
  );
}

/** Brand questions name the company and never a claim: what does AI say it is known for? */
export function BrandQuestions({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const names = probeLabels(run.probes, run.topics);
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const evals = new Map(run.evaluations.map((e) => [e.probe_id, e]));
  const excluded = (id: string) => {
    const a = answers.get(id), e = evals.get(id);
    return !a || !e || !counts(a);
  };
  const raised = new Map<string, AttributeScore[]>();
  for (const s of run.attribute_scores) {
    for (const id of s.probe_ids) raised.set(id, [...(raised.get(id) ?? []), s]);
  }
  const named = run.probes.filter((p) => p.kind === "named" && p.phase === "baseline");
  const withClaims = named.filter((p) => raised.get(p.id)?.some((s) => !s.discovered)).length;
  const d = run.drift;
  return (
    <Section className="qset brand" title={<Term k="brand_question">Branded questions</Term>}
           found={`${named.length} asked · your claims came up in ${withClaims}`
             + (d?.excluded_named ? ` · ${d.excluded_named} excluded` : "")}>
      <details className="qhow">
        <summary>How these were asked ⓘ</summary>
        <p className="muted" style={{ margin: 0 }}>
          Each names {run.profile.name} and never a claim, so whatever AI says it is known for, it said
          unprompted. These answers drive the headline.
        </p>
      </details>
      <div className="qlist">
        {named.map((p) => (
          <QuestionRow key={p.id} p={p} name={names[p.id] ?? p.id} answer={answers.get(p.id)} replay={replay}
                       verdict={excluded(p.id)
                         ? <span className="tag warn">excluded from scores</span>
                         : raised.get(p.id)?.length ? <span className="muted">{plural(raised.get(p.id)!.length, "claim")}</span>
                         : undefined}
                       sub={(raised.get(p.id) ?? []).filter((s) => !s.discovered).map((s) => s.label).join(" · ") || undefined}
                       tags={(raised.get(p.id) ?? []).map((s) => (
                         <span key={s.attribute_id} className={`pill ${s.zone}`}>{s.label}</span>
                       ))} />
        ))}
      </div>
    </Section>
  );
}
