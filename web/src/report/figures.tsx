import { useEffect, useState } from "react";
import type { DriftReport, Run, VisibilitySet } from "../api";
import { headline, provenanceLabel } from "../labels";
import { GLOSSARY } from "../glossary";
import { Popover, Term } from "../popover";
import { FrontMargin } from "../margin";
import { wobbleText, rangeText, FRONT_TERM, frontsOf, gapSentence } from "./util";
import type { Vis } from "./util";
import { Tile } from "./ui";

/** One short label per front. "both": the category AI places you in is the one you aim for. */
export function FrontLabel({ v }: { v: VisibilitySet }) {
  if (v.front === "both") {
    return <><Term k="where_placed">Where AI places you</Term> = <Term k="where_aiming">where you aim to be</Term></>;
  }
  const k = FRONT_TERM[v.front as "placed" | "aiming"];
  return <Term k={k}>{GLOSSARY[k].term}</Term>;
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
 * `explain` puts what the number means, its range and how much one question wobbles between asks,
 * one hover or tap away on the number itself. */
export function Visibility({ d, iv, explain }: { d: Vis; iv?: [number, number] | null; explain?: boolean }) {
  if (d.visibility == null) return <>n/a</>;
  const score = <>{d.visibility}<small> / 100</small></>;
  const note = [rangeText(iv), wobbleText(d)].filter(Boolean).join(". ");
  return (
    <>
      {explain ? <Term k="buyer_visibility" note={note || undefined}>{score}</Term> : score}
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

const still = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A number that counts up once from 0; reduced motion shows it at once. Read aloud as the number. */
function CountUp({ to }: { to: number }) {
  const [at, setAt] = useState(0);
  useEffect(() => {
    if (still()) return;
    const t0 = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / 1100);
      setAt(k < 1 ? to * (1 - (1 - k) ** 3) : to);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  const shown = still() || at === to ? to : at.toFixed(1);
  return <><span aria-hidden="true">{shown}%</span><span className="sr-only">{to}%</span></>;
}

/**
 * The two fronts on one 0–100 buyer-visibility line: a numbered marker each, sliding into place, the
 * likely range of the one that has it shaded, the gap between them dashed. A picture of the line
 * beneath it, which carries every number in words, so it is hidden from screen readers.
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

/** Untapped potential: the number counts up and today's score fills its bar. What it means, its
 * range, what it rests on and the best-case caveat are one hover away. */
export function Headline({ run }: { run: Run }) {
  const d = run.drift!;
  const h = headline(d);
  const brand = run.profile.name;
  const iv = untapped(d[`${h.field}_interval`]);
  if (h.potential == null || h.value == null) {
    return <Tile title={h.label}><span className="hero-num">n/a</span><p>{d.na_reasons?.[h.field]}</p></Tile>;
  }
  return (
    <Tile title={(
      <Popover wide label="Untapped potential" className="term" trigger="Untapped potential">
        <strong className="pop-title">Untapped potential</strong>
        <p>
          The share of {d.lens === "claim"
            ? <>what {brand}’s site says (claims on more pages count for more)</>
            : <>what {brand} wants to be known for (weighted by how much each claim matters)</>}
          {" "}that AI’s answers about {brand} do not yet say supportively.
        </p>
        {iv && <p className="muted">Could be {iv[0]}–{iv[1]}, 95% confident.</p>}
        <p className="muted">
          Based on {d.n_named} branded and {d.n_blind} unbranded answers · source: {provenanceLabel(d.provenance)}
        </p>
        {d.excluded_named > 0 && (
          <p className="muted">
            <strong>A best case:</strong> {d.excluded_named} of {d.named_asked} brand answers were left out, and a
            left-out answer cannot count against {brand}. Read today’s {h.value}% as a best case and the{" "}
            {h.potential}% as a minimum. The reasons are under How we checked on the Evidence page.
          </p>
        )}
      </Popover>
    )}>
      <span className="hero-num"><CountUp to={h.potential} /></span>
      <span className="today-bar" aria-hidden="true"><i style={{ width: `${h.value}%` }} /></span>
      <p>{h.today}</p>
    </Tile>
  );
}

/** Buyer visibility per front: the markers slide into place, the low-confidence badge stays in view,
 * and what each front means, its range and the gap are one hover away. */
export function BuyerVisibility({ run }: { run: Run }) {
  const d = run.drift!;
  const brand = run.profile.name;
  const fronts = frontsOf(d);
  const gap = gapSentence(d, brand);
  const unsure = fronts.filter((v) => v.low_confidence);
  return (
    <Tile wide title={(
      <Popover wide label="Buyer visibility" className="term" trigger={`Does AI bring ${brand} up when buyers ask?`}>
        <strong className="pop-title">{GLOSSARY.buyer_visibility.term}, 0–100</strong>
        <p>{GLOSSARY.buyer_visibility.def}</p>
        {fronts.map((v, i) => (
          <p key={v.front}>
            <strong>{i + 1} · {v.category}:</strong> {FRONT_MEANS[v.front as "placed" | "aiming" | "both"](brand)}{" "}
            {visSaid(v, brand)} {v.visibility != null && (rangeText(v.interval) ?? v.interval_note ?? "One run, no range yet.")}
            {run.sampler && <> · <FrontMargin run={run} front={v.front} /></>}
          </p>
        ))}
        {!fronts.length && <p>{d.visibility == null ? d.na_reasons?.visibility : rangeText(d.visibility_interval) ?? d.na_reasons?.visibility_interval}</p>}
        {gap && <p>{gap}<GapVerdict d={d} /></p>}
        {unsure.length > 0 && (
          <p className="muted">
            <strong>Low confidence:</strong> for each category we also ask AI which companies lead it. If {brand} is
            not among them, a low score says more about what AI knows than about how buyers see {brand}.
          </p>
        )}
      </Popover>
    )}>
      {fronts.length ? (
        <>
          <PositionStrip fronts={fronts} />
          <p className="front-line">
            {fronts.map((v, i) => (
              <span key={v.front}>
                <span className={`front-dot ${v.front}`} aria-hidden="true">{i + 1}</span>
                <strong><Visibility d={v} iv={v.interval} explain /></strong> <FrontLabel v={v} />
              </span>
            ))}
          </p>
        </>
      ) : (
        <p className="front-line"><strong><Visibility d={d} iv={d.visibility_interval} explain /></strong></p>
      )}
    </Tile>
  );
}
