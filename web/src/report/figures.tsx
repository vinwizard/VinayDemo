import type { DriftReport, Run, VisibilitySet } from "../api";
import { headline, plural, provenanceLabel } from "../labels";
import { GLOSSARY } from "../glossary";
import { Term } from "../popover";
import { FrontMargin } from "../margin";
import { wobbleText, rangeText, FRONT_TERM, frontsOf, gapSentence } from "./util";
import type { Vis } from "./util";
import { Logo } from "./ui";

/** One short label per front. "both": the category AI places you in is the one you aim for. */
export function FrontLabel({ v }: { v: VisibilitySet }) {
  if (v.front === "both") {
    return <><Term k="where_placed">Where AI places you</Term> = <Term k="where_aiming">where you aim to be</Term></>;
  }
  const k = FRONT_TERM[v.front as "placed" | "aiming"];
  return <Term k={k}>{GLOSSARY[k].term}</Term>;
}

/** "0–10" beside a number: its bootstrap 95% confidence interval, explained one hover or tap away. */
function Ci({ iv, of }: { iv?: [number, number] | null; of: string }) {
  if (!iv) return null;
  return (
    <Term k="confidence_interval" note={`${of}: between ${iv[0]} and ${iv[1]}, 95% confident.`}>
      <small className="ci">{iv[0]}–{iv[1]}</small>
    </Term>
  );
}

/** The ONE range under a visibility number: where it would land if the whole run were repeated.
 * The per-question wobble is not a second range — it lives in the number's own popover. */
export function Range({ d, iv, note }: { d: Vis; iv?: [number, number] | null; note?: string | null }) {
  if (d.visibility == null) return <>not measured</>;
  const text = rangeText(iv);
  return <Term k="confidence_interval" note={text ? undefined : note}>{text ?? "one run, no range yet"}</Term>;
}

/** The gap's significance test in words: real, not distinguishable, or too few questions to call. */
export function GapVerdict({ d }: { d: DriftReport }) {
  const withheld = d.na_reasons?.visibility_gap_interval;
  if ((d.gap_real == null || !d.gap_interval) && !withheld) return null;
  return (
    <>
      {" "}
      {d.gap_real != null && d.gap_interval ? (
        <Term k="significant_gap" note={`The gap is between ${d.gap_interval[0]} and ${d.gap_interval[1]} points, 95% confident.`}>
          {d.gap_real ? "The gap is real, 95% confident." : "Not distinguishable with this sample."}
        </Term>
      ) : (
        <Term k="significant_gap" note={withheld}>Too few questions to call the gap.</Term>
      )}
    </>
  );
}

/** Buyer visibility, never a bare number when the control question says it is not to be trusted.
 * `explain` puts what the number means, and how much one question wobbles between asks, one hover
 * or tap away on the number itself — so the summary beneath it shows one range, not two. */
export function Visibility({ d, explain }: { d: Vis; explain?: boolean }) {
  if (d.visibility == null) return <>n/a</>;
  const score = <>{d.visibility}<small> / 100</small></>;
  return (
    <>
      {explain ? <Term k="buyer_visibility" note={wobbleText(d)}>{score}</Term> : score}
      {d.low_confidence && <> <Confidence note={d.low_confidence} /></>}
    </>
  );
}

/** A score's interval as untapped potential (100 minus the score), low to high. */
const untapped = (iv?: [number, number] | null): [number, number] | null =>
  iv ? [Math.round((100 - iv[1]) * 10) / 10, Math.round((100 - iv[0]) * 10) / 10] : null;

/** One plain sentence per front: what the category is and where it came from. */
const FRONT_MEANS: Record<"placed" | "aiming" | "both", (brand: string) => string> = {
  placed: (brand) => `The category AI's own answers about ${brand} put it in.`,
  aiming: () => "The category your own homepage puts you in.",
  both: (brand) => `AI's answers about ${brand} put it in the category your homepage aims for.`,
};

/** What buyer visibility said for a front, in one clause, from its own number. */
const visSaid = (v: Vis, brand: string) => v.visibility == null ? null
  : v.visibility === 0 ? `Asked about it without the name, AI never brought ${brand} up.`
  : `Asked about it without the name, AI brought ${brand} up: ${v.visibility} of 100.`;

/** "Low confidence" in amber, never red: a caution about what the number can say, not an error. */
function Confidence({ note }: { note: string }) {
  return <Term k="low_confidence" note={note}><span className="conf">Low confidence</span></Term>;
}

/**
 * The two fronts on one 0–100 buyer-visibility line: a numbered marker each, the likely range of
 * the one that has it shaded, the gap between them dashed. A picture of the rows beneath it, which
 * carry every number in words, so it is hidden from screen readers.
 */
function PositionStrip({ fronts }: { fronts: VisibilitySet[] }) {
  const shown = fronts.filter((v) => v.visibility != null);
  if (!shown.length) return null;
  const at = shown.map((v) => v.visibility as number);
  const lo = Math.min(...at), hi = Math.max(...at);
  return (
    <div className="strip" aria-hidden="true">
      <div className="strip-track" />
      {shown.map((v) => v.interval && (
        <div key={`band-${v.front}`} className={`strip-band ${v.front}`}
             style={{ left: `${v.interval[0]}%`, width: `${Math.max(1, v.interval[1] - v.interval[0])}%` }} />
      ))}
      {shown.length > 1 && hi > lo && (
        <>
          <div className="strip-gap" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
          <span className="strip-gap-label" style={{ left: `${(lo + hi) / 2}%` }}>gap {Math.round((hi - lo) * 10) / 10}</span>
        </>
      )}
      {shown.map((v, i) => (
        <span key={v.front} className={`strip-mark ${v.front}`} style={{ left: `${v.visibility}%` }}>{i + 1}</span>
      ))}
      {[0, 50, 100].map((t) => <span key={t} className="strip-tick" style={{ left: `${t}%` }}>{t}</span>)}
    </div>
  );
}

/** One front as a row under the strip: its marker, label and category, its score, and what it means. */
function FrontRow({ v, n, brand, run }: { v: VisibilitySet; n: number; brand: string; run?: Run }) {
  return (
    <div className="front-row">
      <span className={`front-dot ${v.front}`} aria-hidden="true">{n}</span>
      <div className="front-name"><FrontLabel v={v} />: <strong>{v.category}</strong></div>
      <span className="front-score"><Visibility d={v} explain /></span>
      <p className="front-means">
        {FRONT_MEANS[v.front as "placed" | "aiming" | "both"](brand)} {visSaid(v, brand)}
        {" "}<Range d={v} iv={v.interval} note={v.interval_note} />
        {run?.sampler && <> · <FrontMargin run={run} front={v.front} /></>}
      </p>
    </div>
  );
}

/** The headline, buyer visibility and the quick wins. The whole block scrolls with the page; once it
 * is out of view a one-line summary pins itself above the tabs (Report). */
export function Figures({ d, brand, run, onQuickWins }: { d: DriftReport; brand: string; run?: Run; onQuickWins?: () => void }) {
  const h = headline(d);
  const wins = d.lost_claims.length + d.unstated_intent.length;  // the Quick wins tab's claims
  const fronts = frontsOf(d);
  const gap = gapSentence(d, brand, true);
  const unsure = fronts.filter((v) => v.low_confidence);
  return (
    <div className="figures">
      <div className="fig-card headline" data-tour="headline">
        <span className="hero-num">
          {h.potential == null ? "n/a" : <>{h.potential}%</>}
        </span>
        <span className="fig-label">
          {h.potential == null ? h.label : <Term k="untapped_potential">Untapped potential</Term>}
        </span>
        <span>{h.today ?? d.na_reasons?.[h.field]}</span>
        {h.potential != null && untapped(d[`${h.field}_interval`]) && (
          <span className="muted">Could be <Ci iv={untapped(d[`${h.field}_interval`])} of="Untapped potential" /></span>
        )}
        {wins > 0 && (
          <span className="row" style={{ gap: ".3rem" }}>
            <button type="button" className="chip-link" onClick={onQuickWins}>{plural(wins, "quick win")} →</button>
            <Term k="quick_wins" icon />
          </span>
        )}
      </div>
      <div className="fig-card fronts" data-tour="fronts">
        <div className="fronts-head">
          <strong>Does AI bring {brand} up when buyers ask?</strong>
          <span className="muted"><Term k="buyer_visibility">buyer visibility</Term>, 0–100</span>
        </div>
        {fronts.length ? (
          <>
            <PositionStrip fronts={fronts} />
            {fronts.map((v, i) => <FrontRow key={v.front} v={v} n={i + 1} brand={brand} run={run} />)}
            {gap && <p className="gap-line">{gap}<GapVerdict d={d} /></p>}
            {unsure.length > 0 && (
              <details className="conf-explain">
                <summary>What does “low confidence” mean here?</summary>
                <p>For each category we also ask AI which companies lead it. If {brand} is not among them, a low
                  score says more about what AI knows than about how buyers see {brand}.</p>
                {unsure.map((v) => <p key={v.front} className="muted"><strong>{v.category}:</strong> {v.low_confidence}</p>)}
              </details>
            )}
          </>
        ) : (
          <div className="front-row">
            <span className="front-score"><Visibility d={d} explain /></span>
            <p className="front-means">
              {d.visibility == null ? d.na_reasons?.visibility
                : <Range d={d} iv={d.visibility_interval} note={d.na_reasons?.visibility_interval} />}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/** The one line that stays pinned once the header has scrolled away: the headline and each front. */
export function PinnedLine({ d, run }: { d: DriftReport; run: Run }) {
  const h = headline(d);
  const fronts = frontsOf(d).filter((v) => v.visibility != null);
  return (
    <div className="pinned-line">
      <Logo name={run.profile.name} url={run.profile.logo_url} size={22} />
      <strong>{run.profile.name}</strong>
      {h.potential != null && <span><strong>{h.potential}%</strong> untapped</span>}
      {fronts.length > 0 && (
        <span className="muted">buyer visibility {fronts.map((v) => v.visibility).join(" → ")}</span>
      )}
    </div>
  );
}

/** What the pinned figures mean, in plain words with every invented term defined in place. */
export function Explain({ d, brand }: { d: DriftReport; brand: string }) {
  return (
    <p className="muted" style={{ margin: 0 }}>
      <Term k="untapped_potential">Untapped potential</Term> is the share of{" "}
      {d.lens === "claim"
        ? <>what {brand}’s site says (claims on more pages count for more)</>
        : <>what {brand} wants to be known for (weighted by how much each claim matters)</>}
      {" "}that AI’s answers about {brand} do not yet say supportively.{" "}
      <Term k="buyer_visibility">Buyer visibility</Term> is a separate score: how often {brand} came up
      when a buyer asked without naming it.
      {" "}Based on {d.n_named} <Term k="brand_question">branded question</Term> answers and{" "}
      {d.n_blind} <Term k="buyer_question">unbranded question</Term> answers · source: {provenanceLabel(d.provenance)}
    </p>
  );
}
