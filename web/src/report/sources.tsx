import { useState } from "react";
import type { Run } from "../api";
import { probeLabels, plural } from "../labels";
import { PHONE, Term } from "../popover";
import { counts, mention, listed, placeholder } from "./util";
import type { Source } from "./util";
import { Logo, Block, Section, SAMPLE_NOTE } from "./ui";
import { QuestionRow } from "./questions";

/**
 * Every company named in a buyer answer, beside the line that names it, and what AI said when asked
 * to compare.
 *
 * A name here is only what the evidence supports: the model named it in an answer to a question that
 * never named the company. Many such names are obscure products a search happened to surface, or a
 * citation's hostname, so the panel neither calls them competitors nor claims they were recommended
 * — the line is shown so the reader judges each one. It ranks only when a name genuinely repeats
 * across answers; when each appears once, any order would just be the first answer's order.
 *
 * In replay the names are authored fixture labels and the panel says so — a sentence asserting
 * measured behaviour is believed over the banner at the top of the page, and this product's whole
 * claim is that it never presents authored evidence as measured evidence.
 */
export function Competitors({ run }: { run: Run }) {
  const replay = run.mode !== "live_api";
  const topicOf = new Map(run.topics.map((t) => [t.id, t.label]));
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  const evals = new Map(run.evaluations.map((e) => [e.probe_id, e]));
  const named = new Map<string, { name: string; count: number; topic: string;
                                   where: [string, string, string] | null }>();
  for (const p of run.probes.filter((x) => x.kind === "blind" && x.phase === "baseline")) {
    const a = answers.get(p.id), e = evals.get(p.id);
    if (!a || !e || !counts(a)) continue;
    for (const name of new Set(e.competitor_recommendations)) {
      const row = named.get(name.toLowerCase());
      if (row) row.count += 1;
      else named.set(name.toLowerCase(), { name, count: 1, topic: topicOf.get(p.topic_id) ?? p.topic_id,
                                           where: mention(a.text, name) });
    }
  }
  const repeats = [...named.values()].some((r) => r.count > 1);
  // A stable sort: names seen once keep the order they appeared in.
  const rows = [...named.values()].sort((x, y) => (repeats ? y.count - x.count : 0));
  const comparison = run.probes.find((p) => p.kind === "named" && p.phase === "followup");
  const answer = comparison && answers.get(comparison.id);
  // "Nobody was named" and "nobody was asked" are different findings. With no weighted claim there
  // are no buyer questions at all, and an empty set then means silence, not absence.
  const askedBuyerQuestions = run.probes.some((p) => p.kind === "blind" && p.phase === "baseline");
  const title = "Who AI named instead";
  if (!rows.length) {
    return (
      <Section title={title} found="none named">
        <p className="muted" style={{ margin: 0 }}>
        {!askedBuyerQuestions
          ? "No unbranded question was asked — nothing is weighted as intended — so the buyer axis was not measured and no other company could be named."
          : replay
            ? "This sample scenario names no competitor in its authored buyer answers. Replay never asks the comparison question either: that round exists only in a live run."
            : "No other company was named in any buyer answer that counts toward the scores, so there was nothing to compare against and no comparison question was asked."}
        </p>
      </Section>
    );
  }
  const top = rows[0];
  const namedTable = (shown: typeof rows) => (
    <table className="named">
      <thead>
        <tr><th>Company</th>{repeats && <th>Answers</th>}<th>Buyer topic</th><th>Where the answer names it</th></tr>
      </thead>
      <tbody>
        {shown.map((r) => (
          <tr key={r.name}>
            <td><strong>{r.name}</strong></td>
            {repeats && <td>{r.count}</td>}
            <td className="muted">{r.topic}</td>
            <td className="muted">
              {r.where ? <>{r.where[0]}<strong>{r.where[1]}</strong>{r.where[2]}</> : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <Section title={title}
           found={`${plural(rows.length, "company", "companies")} named${repeats ? ` · most often ${top.name} (${top.count})` : ""}`}>
      <p className="muted" style={{ margin: "0 0 .6rem" }}>
        {replay
          ? "Authored sample data, not a measurement: no model volunteered these names. A live run"
            + " puts here the brands the model itself offered when a buyer described what you do"
            + " without naming you, and only a live run asks the comparison question below."
          : `Every company the model named when a buyer asked about what ${run.profile.name} does`
            + " without naming it. Being named is not being recommended, or being a competitor:"
            + " each sits beside the part of the answer that names it, so judge it yourself."}
        {" "}
        {repeats
          ? "Sorted by how many answers named it; the rest were named once, in the order they appeared."
          : "Each was named in one answer only, so this is the order they appeared, not a ranking."}
      </p>
      {namedTable(rows.slice(0, SHOWN_NAMED))}
      {rows.length > SHOWN_NAMED && (
        <details>
          <summary className="muted">Show the other {plural(rows.length - SHOWN_NAMED, "company", "companies")}</summary>
          {namedTable(rows.slice(SHOWN_NAMED))}
        </details>
      )}
      {comparison && (
        <>
          <h4 className="muted" style={{ marginTop: "1rem" }}>
            Follow-up question, built from those names (exploratory — not counted in alignment)
          </h4>
          <QuestionRow p={comparison} name="Follow-up" answer={answer || undefined} replay={replay} />
        </>
      )}
    </Section>
  );
}

/** Brand vs the most-recommended competitors, on the buyer questions that count. One bar per name. */
export function ShareOfVoice({ run }: { run: Run }) {
  const v = run.insights?.voice;
  const title = <><Term k="share_of_voice">Share of voice</Term> on unbranded questions</>;
  if (!v) return null;
  if (v.reason) {
    return (
      <Section title={title} found="not measured">
        <p className="muted" style={{ margin: 0 }}>{v.reason}</p>
      </Section>
    );
  }
  const top = v.rivals.filter((r) => r.count === v.rivals[0].count);
  const others = v.tied_top - top.length;
  const rivalText = v.tied_top > 1
    ? `${listed([...top.map((r) => r.name), ...(others ? [plural(others, "other")] : [])])} ${v.rivals[0].count} each`
    : `${top[0].name} ${plural(top[0].count, "time")}`;
  const bars = [{ name: v.brand, count: v.brand_recommended, brand: true },
                ...v.rivals.map((r) => ({ ...r, brand: false }))];
  return (
    <Section title={title}
           found={`On ${v.questions} unbranded questions, AI recommended ${v.brand} ${plural(v.brand_recommended, "time")} and ${rivalText}`}>
      <p className="muted" style={{ margin: 0 }}>
        {run.mode !== "live_api" && <>{SAMPLE_NOTE} </>}
        How many of the {v.questions} unbranded questions that count got an answer recommending each company. None
        of those questions named {v.brand}; a mention without a recommendation does not count, and a company
        counts once per answer, however often it repeats.
      </p>
      <div className="sov" role="list" aria-label={`Answers recommending each company, out of ${v.questions}`}>
        {bars.map((b) => (
          <div key={b.name} role="listitem" className="sov-row" title={`${b.name}: recommended in ${b.count} of ${v.questions} answers`}>
            <span className={b.brand ? "sov-name brand" : "sov-name"}>{b.name}</span>
            <span className="sov-track">
              <span className={b.brand ? "sov-bar brand" : "sov-bar"} style={{ width: `${(100 * b.count) / v.questions}%` }} />
            </span>
            <span className="sov-count">{b.count} / {v.questions}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

const SHOWN_NAMED = 3;

const KIND_LABEL: Record<Source["kind"], string> = {
  owned: "your site", rival: "a rival's site", review: "review site", community: "community",
  media: "media or blog", other: "other site",
};
const SHOWN_GAPS = 6;
/** Up to four rival initials in a row, the rest as "+n"; each names its rival on hover. */
function Avatars({ rivals }: { rivals: Source["rivals"] }) {
  const shown = rivals.slice(0, 4);
  return (
    <span className="avatars" title={rivals.map((r) => r.name).join(", ")}>
      {shown.map((r) => <Logo key={r.name} name={r.name} size={22} />)}
      {rivals.length > shown.length && <span className="avatars-more">+{rivals.length - shown.length}</span>}
      <span className="sr-only">{listed(rivals.map((r) => r.name))}</span>
    </span>
  );
}

/** One site that AI cites beside rivals but never beside the brand; opening it shows the answers that cited it. */
function GapSource({ r, rank, run, names }: { r: Source; rank: number; run: Run; names: Record<string, string> }) {
  const probes = new Map(run.probes.map((p) => [p.id, p]));
  const answers = new Map(run.answers.map((a) => [a.probe_id, a]));
  return (
    <details className="src">
      <summary>
        <span className="src-rank">{rank}</span>
        <span className="src-name">
          <strong>{r.domain}</strong>
          <span className="muted">{KIND_LABEL[r.kind]} · {plural(r.buyer, "buyer answer")}</span>
        </span>
        <Avatars rivals={r.rivals} />
      </summary>
      <div className="src-body">
        <p style={{ margin: 0 }}>
          Cited beside {listed(r.rivals.map((x) => x.count > 1 ? `${x.name} (${x.count})` : x.name))},
          never in an answer that mentions {run.profile.name}.
        </p>
        <p className="muted" style={{ margin: 0 }}>
          <Term k="source_type">Site type</Term>: {KIND_LABEL[r.kind]}
          {!placeholder(r.domain) && <> · <a href={r.url} target="_blank" rel="noreferrer">open the page</a></>}
        </p>
        <div>
          {r.probes.map((id) => probes.get(id) && (
            <QuestionRow key={id} p={probes.get(id)!} name={names[id] ?? id} answer={answers.get(id)}
                         replay={run.mode !== "live_api"} />
          ))}
        </div>
      </div>
    </details>
  );
}

/**
 * Who AI trusts in this category: the sites it cited in buyer answers, and which brands each one sat
 * beside. The ranked list of sites cited beside rivals but never beside the brand comes first; the
 * full list of cited sites is one tap away. Replaces the plain cited-sites table.
 */
export function CitationNetwork({ run }: { run: Run }) {
  const s = run.insights?.sources;
  const [open] = useState(() => !window.matchMedia(PHONE).matches);
  if (!s) return null;
  const brand = run.profile.name;
  const sample = run.mode !== "live_api"
    && <>{SAMPLE_NOTE} Every example.com address is a fictional placeholder. </>;
  if (s.reason) {
    return <Block open={open} className="finding" title="No cited sources to map" found={null}>
      <p className="muted" style={{ margin: 0 }}>{s.reason}</p>
    </Block>;
  }
  const by = new Map(s.sources.map((r) => [r.domain, r]));
  const gaps = (s.rival_only ?? []).map((d) => by.get(d)!).filter(Boolean);
  const names = probeLabels(run.probes, run.topics);
  const title = gaps.length
    ? `AI cited ${plural(gaps.length, "site")} beside your rivals, never beside ${brand}`
    : s.sources.some((r) => r.rivals?.length && r.kind !== "owned" && r.kind !== "rival")
      ? `Every third-party site AI cited beside a rival was cited beside ${brand} too`
      : `AI cited ${plural(s.sources.length, "site")}, no third-party site beside a rival`;
  const gapRow = (r: Source, i: number) => <GapSource key={r.domain} r={r} rank={i + 1} run={run} names={names} />;
  return (
    <Block open={open} className="finding" title={<>{title} <Term k="rival_only" icon /></>} found={null}>
      <p className="muted" style={{ margin: 0 }}>
        {sample}
        {gaps.length
          ? <>These were cited in buyer answers that named a rival and never mentioned {brand}: the pages
             to get onto. Tap one for the answers.</>
          : <>A site cited beside rivals but never beside {brand} would be listed here as a page to get onto.</>}
        {" "}A citation shows what the model read, not why it answered as it did.
      </p>
      {gaps.length > 0 && <div className="src-list">{gaps.slice(0, SHOWN_GAPS).map(gapRow)}</div>}
      {gaps.length > SHOWN_GAPS && (
        <details className="more">
          <summary className="muted">Show {plural(gaps.length - SHOWN_GAPS, "more site")}</summary>
          <div className="src-list">{gaps.slice(SHOWN_GAPS).map((r, i) => gapRow(r, i + SHOWN_GAPS))}</div>
        </details>
      )}
      <details className="more">
        <summary className="muted">
          All {plural(s.sources.length, "cited site")} · cited in {s.cited_answers} of {s.answers} buyer and brand answers
        </summary>
        <table className="named">
          <thead>
            <tr><th>Site</th><th>Answers</th><th>Cited beside</th></tr>
          </thead>
          <tbody>
            {s.sources.map((r) => (
              <tr key={r.domain}>
                <td><strong>{r.domain}</strong><br /><span className="muted">{r.rival ? `${r.rival}'s site` : KIND_LABEL[r.kind] ?? "other site"}</span></td>
                <td>{r.answers}<br /><span className="muted">{r.buyer} buyer · {r.brand} brand</span></td>
                <td className="muted">
                  {[...(r.with_brand ? [`${brand} (${r.with_brand})`] : []),
                    ...(r.rivals ?? []).map((x) => `${x.name} (${x.count})`)].join(", ") || "no brand named"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </Block>
  );
}
