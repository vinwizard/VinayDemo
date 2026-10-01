import { useState } from "react";
import type { AttributeScore, Run } from "../api";
import { GAP_ZONES, OWNER_TEXT, OWNER_TITLE, ZONE_ORDER, ZONES, rescoreRun } from "../api";
import { ADDED_MIN_WEIGHT, Slider } from "../claims";
import { ZONE_LABEL, headline, plain, plural } from "../labels";
import { GLOSSARY } from "../glossary";
import { Popover, Term } from "../popover";
import { ZONE_FILL, pct, siteShare, aiShare, leftOut, refs, sortClaims, winBackPlan } from "./util";
import { Block, Section } from "./ui";
import { Linked } from "./questions";
import { FixCard } from "./winback";

/**
 * The six zones as chips with counts. Each opens a popover listing its claims — site share, AI
 * share, the AI's own words, the questions behind them and the fix — scrolling when there are many.
 * An empty zone is greyed but still says what it means.
 */
export function ZoneChips({ run }: { run: Run }) {
  const sorted = sortClaims(run.attribute_scores);
  return (
    <Section title="Your claims, grouped by what AI does with them" found="hover or tap a group to see its claims">
      <div className="chips" role="list" data-tour="zones">
        {ZONES.map((z) => {
          const rows = sorted.filter((s) => s.zone === z);
          return (
            <div role="listitem" key={z}>
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
    </Section>
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
 * Intent weights on the finished run. The server re-scores the saved answers — no question is
 * re-asked and no model is called — and refuses (409) a run it cannot re-score, in its own words.
 */
export function Weights({ run, onRescored }: { run: Run; onRescored: (r: Run) => void }) {
  const claims = run.attribute_scores.filter((s) => !s.discovered);
  const added = new Set((run.attributes ?? []).filter((a) => a.added_by_user).map((a) => a.id));
  const [w, setW] = useState<Record<string, number>>(
    () => Object.fromEntries(claims.map((s) => [s.attribute_id, s.intended_weight ?? 0])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const weighted = claims.filter((s) => (s.intended_weight ?? 0) > 0).length;
  const submit = () => {
    setBusy(true); setError(null);
    rescoreRun(run.id, w).then(onRescored).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  return (
    <Block title="Optional: weight what you want to be known for"
           found={weighted ? `${plural(weighted, "claim")} weighted · headline is alignment`
             : "nothing weighted · headline is claim echo"}>
      <p className="lede">
        Move a slider for each claim you want to be known for, then re-score. This re-scores this
        run’s saved answers: <strong>no new AI calls are made</strong>, nothing is paid, and no
        question is re-asked.
      </p>
      <div className="weights">
        {claims.map((s) => (
          <div className="weight-row" key={s.attribute_id}>
            <span>{s.label}</span>
            <Slider id={`rw-${run.id}-${s.attribute_id}`} label={`Intent for ${s.label}`}
                    min={added.has(s.attribute_id) ? ADDED_MIN_WEIGHT : 0}
                    value={w[s.attribute_id] ?? 0} disabled={busy}
                    onChange={(v) => setW((x) => ({ ...x, [s.attribute_id]: v }))} />
          </div>
        ))}
      </div>
      {error && <div className="callout error">{error}</div>}
      <div className="row">
        <button className="primary" onClick={submit} disabled={busy}>
          {busy ? "Re-scoring…" : "Re-score this run"}
        </button>
        <span className="muted">Re-scores saved answers only — no new AI calls.</span>
      </div>
    </Block>
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

/** Every claim as a card; hovering or tapping one shows everything about it in place. */
function ClaimCards({ scores, run }: { scores: AttributeScore[]; run: Run }) {
  return (
    <div className="claim-cards">
      {sortClaims(scores).map((s) => (
        <Popover key={s.attribute_id} wide label={s.label} className="claim-card"
                 trigger={<>
                   <span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span>
                   <strong>{s.label}</strong>
                   <AiBar s={s} />
                   <span className="muted">Site: {siteShare(s)}</span>
                   <span className="muted">AI: {aiShare(s)}</span>
                   <span className="muted">{standing(s)}</span>
                 </>}>
          <ClaimDetail s={s} run={run} />
        </Popover>
      ))}
    </div>
  );
}

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

/** "Where the upside is": the biggest open claims first, one compact row each. The diagnosis they
 * share is said once; each row opens everything about its claim. */
export function UpsideTable({ run }: { run: Run }) {
  const gaps = run.attribute_scores
    .filter((s) => GAP_ZONES.includes(s.zone))
    .sort((a, b) => ZONE_ORDER[a.zone] - ZONE_ORDER[b.zone] || (b.intended_weight ?? 0) - (a.intended_weight ?? 0))
    .slice(0, 4);
  if (!gaps.length) {
    return <div className="card muted">No open opportunity: every claim has landed or is unweighted.</div>;
  }
  const owners = [...new Set(gaps.map((s) => s.owner))];
  const shared = owners.length === 1 ? owners[0] : null;
  return (
    <div className="stack" style={{ gap: ".5rem" }}>
      {shared && (
        <p style={{ margin: 0 }}>
          {gaps.length > 1 ? `All ${gaps.length} are` : "It is"} <strong>{OWNER_TITLE[shared].toLowerCase()}s</strong>: {OWNER_TEXT[shared]}
          {shared === "messaging_gap" && " Not an AI problem: your own copy does not state this clearly enough to be repeated."}
        </p>
      )}
      <div className="table-scroll">
        <table className="compact">
          <thead><tr><th>Claim</th><th>Type</th>{!shared && <th>Why</th>}<th>Your site</th><th>AI</th></tr></thead>
          <tbody>
            {gaps.map((s) => (
              <tr key={s.attribute_id}>
                <td><Popover wide label={s.label} className="linky row-open" trigger={s.label}><ClaimDetail s={s} run={run} /></Popover>
                  {s.discovered && <span className="muted"> (AI's own)</span>}
                  {s.quotes[0] && <p className="quote small-quote">{plain(s.quotes[0])}</p>}
                  {s.limitations.filter((l) => l.includes("does not endorse it")).map((l, i) => <p className="warn" key={i} style={{ margin: 0 }}>{l}</p>)}
                </td>
                <td><Term k={s.zone}><span className={`pill ${s.zone}`}>{ZONE_LABEL[s.zone]}</span></Term></td>
                {!shared && <td><strong>{OWNER_TITLE[s.owner]}.</strong> {OWNER_TEXT[s.owner]}</td>}
                <td>{s.discovered ? "Found in the answers, not on the site" : siteShare(s)}</td>
                <td>{aiShare(s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ margin: 0 }}>Open a claim for AI's own words and all its evidence.</p>
    </div>
  );
}

/** Things AI says the company is known for that neither the company nor its site ever supplied. */
export function Discovered({ run }: { run: Run }) {
  const found = run.attribute_scores.filter((s) => s.discovered);
  const toShape = found.filter((s) => s.zone === "imposed").length;
  return (
    <Section title={<>Discovered <Term k="imposed">identities</Term></>}
           found={found.length ? `${found.length} found in the answers${toShape ? ` · ${toShape} to shape` : ""}`
             : "none found"}>
      {found.length ? (
        <>
          <p className="muted" style={{ margin: 0 }}>
            Found in the answers by the discovery pass — never supplied by you or your site. Each is
            an identity AI already gives {run.profile.name}: adopt it, or reframe it.
          </p>
          <ClaimCards scores={found} run={run} />
        </>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          The answers raised nothing about {run.profile.name} beyond the claims on the Overview.
        </p>
      )}
    </Section>
  );
}
