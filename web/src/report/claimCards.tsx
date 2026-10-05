import type { CSSProperties } from "react";
import type { AttributeScore, Run } from "../api";
import { OWNER_TEXT, OWNER_TITLE, ZONES } from "../api";
import { ZONE_LABEL, headline, plain, plural } from "../labels";
import { GLOSSARY } from "../glossary";
import { Popover, Term } from "../popover";
import { ZONE_FILL, pct, siteShare, aiShare, leftOut, refs, sortClaims, winBackPlan } from "./util";
import { Tile } from "./ui";
import { Linked } from "./questions";
import { FixCard } from "./winback";

/**
 * The six zones as chips with counts, popping in one after another. Each opens a popover listing its
 * claims — site share, AI share, the AI's own words, the site's own words, which gap it is, and the
 * fix — scrolling when there are many. An empty zone is greyed but still says what it means.
 */
export function ZoneChips({ run }: { run: Run }) {
  const sorted = sortClaims(run.attribute_scores);
  return (
    <Tile wide tour="zones" title="Your claims, by what AI does with them">
      <div className="chips zone-chips" role="list">
        {ZONES.map((z, i) => {
          const rows = sorted.filter((s) => s.zone === z);
          return (
            <div role="listitem" key={z} style={{ "--i": i } as CSSProperties}>
              <Popover wide label={`${GLOSSARY[z].term}: ${plural(rows.length, "claim")}`}
                       className={`chip ${rows.length ? "" : "zero"}`}
                       trigger={<><span className="dot" style={{ background: ZONE_FILL[z] }} />{ZONE_LABEL[z]}
                                  <span className="chip-count">{rows.length}</span></>}>
                <strong className="pop-title">{GLOSSARY[z].term} · {plural(rows.length, "claim")}</strong>
                <p className="muted">{GLOSSARY[z].def}</p>
                {rows.length ? rows.map((s) => <ClaimDetail key={s.attribute_id} s={s} run={run} />)
                  : <p className="muted">No claim is in this group in this run.</p>}
              </Popover>
            </div>
          );
        })}
      </div>
    </Tile>
  );
}

/**
 * The excluded brand answers, in plain words: how many the headline rests on, why each was left out
 * (each question readable in place), and which way that tilts the number.
 */
export function Excluded({ run }: { run: Run }) {
  const d = run.drift!;
  if (!d.excluded_named) return null;
  const brand = run.profile.name;
  const h = headline(d);
  const byReason = new Map<string, string[]>();
  for (const p of run.probes.filter((x) => x.kind === "named" && x.phase === "baseline")) {
    const why = leftOut(run.answers.find((a) => a.probe_id === p.id), run.evaluations.find((e) => e.probe_id === p.id), brand);
    if (why) byReason.set(why, [...(byReason.get(why) ?? []), p.id]);
  }
  const found = [...byReason.values()].flat().length;
  const them = d.excluded_named === 1 ? "it" : "them";
  return (
    <div className="callout excluded">
      <h4>Based on {d.n_named} of {d.named_asked} brand answers</h4>
      <p>
        {found === d.excluded_named
          ? [...byReason].map(([why, ids], i) => (
              <span key={why}>{i ? " " : ""}For {ids.length === 1 ? "one question" : `${ids.length} questions`} ({refs(ids, run)}), {why}.</span>
            ))
          : <>Left out: {d.excluded_reasons.map((r, i) => <span key={i}>{i ? "; " : ""}<Linked text={r} run={run} /></span>)}.</>}
        {" "}We left {them} out rather than guess what {them === "it" ? "it" : "they"} would have said.
      </p>
      <p className="muted">
        A left-out answer cannot count against {brand}, so this can only flatter it
        {h.value != null ? <>: read today’s {h.value}% as a best case, and the {h.potential}% untapped potential as a minimum.</> : "."}
      </p>
    </div>
  );
}

/**
 * How AI raises a claim. Total width is how OFTEN AI raises it. The zone-coloured segment is
 * endorsements (echo_rate, what drives landed and alignment), the grey one neutral mentions, and
 * the red one criticism.
 */
function AiBar({ s }: { s: AttributeScore }) {
  return (
    <span className="bar-track thin" aria-hidden>
      <span className="bar" style={{ width: `${pct(s.echo_rate)}%`, background: ZONE_FILL[s.zone] }} />
      <span className="bar" style={{ width: `${Math.max(0, pct(s.mention_rate) - pct(s.echo_rate) - pct(s.negative_rate))}%`, background: "#c9d1d9" }} />
      <span className="bar neg" style={{ width: `${pct(s.negative_rate)}%` }} />
    </span>
  );
}

const standing = (s: AttributeScore) =>
  s.discovered ? "discovered from the answers"
    : s.intended_weight ? `intent ${s.intended_weight}`
    : s.claim_pages > 0 || (s.claim_strength ?? 0) > 0 ? "on your site, not weighted"
    : "not claimed by you";

/**
 * Everything about one claim: what the site says, what AI said and where, and its win-back fix.
 * One row in a zone chip's popover; every question it cites opens in place.
 */
export function ClaimDetail({ s, run }: { s: AttributeScore; run: Run }) {
  const site = (run.attributes ?? []).find((a) => a.id === s.attribute_id);
  const fix = winBackPlan(run).actions.find((a) => a.attribute_id === s.attribute_id);
  return (
    <div className="claim-row">
      <div className="claim-row-head">
        <strong>{s.label}</strong>
        <span className="muted">{standing(s)}</span>
      </div>
      {s.description && <p>{s.description}</p>}
      <AiBar s={s} />
      <p className="muted">Your site: {siteShare(s)}</p>
      <p className="muted">AI: {aiShare(s)} <Term k="endorsed" icon /></p>
      {s.quotes.length > 0 ? (
        <>
          <h4>In the AI’s own words</h4>
          {s.quotes.map((q, i) => <p className="quote" key={i}>{plain(q)}</p>)}
        </>
      ) : <p className="muted">No word-for-word quote from an AI answer supports this claim.</p>}
      {s.probe_ids.length > 0 && <p className="muted">Raised in {refs(s.probe_ids, run)}.</p>}
      {site && site.claim_quotes.length > 0 && (
        <>
          <h4>What your site says</h4>
          {site.claim_quotes.map((q, i) => <p className="quote" key={i}>{q}</p>)}
        </>
      )}
      <p><strong>{OWNER_TITLE[s.owner]}.</strong> {OWNER_TEXT[s.owner]}</p>
      {s.limitations.map((l, i) => <p className="warn" key={i}>{l}</p>)}
      {fix && (
        <>
          <h4>Quick win</h4>
          <FixCard a={fix} run={run} />
        </>
      )}
    </div>
  );
}
