import type { FrontSample, Run } from "./api";
import { Term } from "./popover";

/**
 * One front's sampler-lite result in a line: the share of buyer questions that named the company,
 * its margin at 95%, and how many of the frozen questions it took to get there.
 */
export function FrontMargin({ run, front }: { run: Run; front?: FrontSample["front"] }) {
  const s = run.sampler;
  const f = s?.fronts.find((x) => x.front === front);
  if (!s || !f || f.rate == null || !f.interval) return null;
  const half = Math.round((f.interval[1] - f.interval[0]) / 2);
  return (
    <span className="front-margin">
      named you in {Math.round(f.rate)}% of them{" "}
      <Term k="margin" note={`Between ${f.interval[0]}% and ${f.interval[1]}%, 95% confident.`}>
        ±{half}{f.margin_met ? "" : ` (target ±${s.margin} not met)`}
      </Term>
      {" "}· {f.asked} of {f.pool} questions{f.stopped_early ? ", clear after the first look" : ""}
      {f.note && <> · <span className="warn">{f.note}</span></>}
    </span>
  );
}

/** How the run's buyer questions were spent, in one sentence under the unbranded questions. */
export function SamplerNote({ run }: { run: Run }) {
  const s = run.sampler;
  if (!s) return null;
  const early = s.fronts.filter((f) => f.stopped_early).length;
  return (
    <p className="muted" style={{ margin: 0 }}>
      Each front aimed for a <Term k="margin">margin</Term> of ±{s.margin} points at 95%: {s.looks[0]} fresh
      questions first, up to {s.looks[1]} only where the answers so far were not clear
      {early ? ` (${early} front${early === 1 ? "" : "s"} were clear after the first look)` : ""}.
      {s.shared > 0 && <> {s.shared} <Term k="shared_answer">answers were reused</Term> from a run in the last 24
        hours.</>}
    </p>
  );
}
