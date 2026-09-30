import type { ReactNode } from "react";
import type { Run } from "../api";
import { plural } from "../labels";
import { Term } from "../popover";
import { Linked } from "./questions";

const DROPPED = "Dropped unverifiable observation — ";
const DISCOVERY = "Discovery — ";

/** One dropped reading of an answer, as "Brand question 3 — the quote … did not match word for word". */
function DroppedLine({ text, run }: { text: string; run: Run }) {
  const m = /^(.*?): (?:Attribute (\S+): quote (not verbatim|is from a citation)|Unknown attribute id '([^']+)')/.exec(text);
  if (!m) return <Linked text={text} run={run} />;
  const label = (id: string) => run.attribute_scores.find((s) => s.attribute_id === id)?.label ?? id.replaceAll("_", " ");
  return (
    <>
      <Linked text={m[1]} run={run} /> —{" "}
      {m[3] === "not verbatim" ? <>the quote for “{label(m[2])}” did not match the answer word for word</>
        : m[3] ? <>the quote for “{label(m[2])}” came from a cited source, not the answer</>
        : <>it named “{label(m[4])}”, a trait this run was not measuring</>}
    </>
  );
}

/** One possible new trait the answers suggested, and why it was not kept. */
function DiscoveryLine({ text, run }: { text: string; run: Run }) {
  const m = /^'(.+?)': (.*)$/.exec(text);
  if (!m) return <Linked text={text} run={run} />;
  const thin = /in (\d+) eligible answer\(s\), needs (\d+)/.exec(m[2]);
  return (
    <>
      “{m[1]}” —{" "}
      {thin ? `found word for word in only ${plural(Number(thin[1]), "answer")}; it needs ${thin[2]}`
        : m[2].startsWith("same attribute") ? "the same as a trait already measured"
        : <Linked text={m[2]} run={run} />}
    </>
  );
}

/** A count with its items one small toggle away. */
function Count({ summary, items }: { summary: ReactNode; items: ReactNode[] }) {
  if (!items.length) return <li>{summary}</li>;
  return (
    <li>
      <details>
        <summary>{summary}</summary>
        <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
      </details>
    </li>
  );
}

/** The whole run as JSON, workflow log included: the page shows the checks, the file keeps every step. */
function downloadRun(run: Run) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${run.profile.name.replace(/\W+/g, "-")}-${run.id}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * "How we checked this report": the drift limitations, excluded answers, dropped observations and
 * discovery notes turned into a few counts in plain sentences, each with its items behind a toggle.
 * The raw workflow log stays out of the page and in the downloadable data.
 */
export function HowWeChecked({ run }: { run: Run }) {
  const d = run.drift!;
  const lim = d.limitations;
  const dropped = lim.filter((l) => l.startsWith(DROPPED)).map((l) => l.slice(DROPPED.length));
  const notVerbatim = dropped.filter((l) => l.includes("quote not verbatim")).length;
  const cited = dropped.filter((l) => l.includes("quote is from a citation")).length;
  const unknown = dropped.filter((l) => l.includes("Unknown attribute id")).length;
  const otherDrop = dropped.length - notVerbatim - cited - unknown;
  const discovery = lim.filter((l) => l.startsWith(DISCOVERY)).map((l) => l.slice(DISCOVERY.length));
  const proposals = discovery.filter((l) => /^'.+?': /.test(l));
  const rejected = proposals.filter((l) => !l.includes(": kept on its verbatim answers"));
  const thin = rejected.filter((l) => / needs \d+/.test(l)).length;
  const repeats = rejected.filter((l) => l.includes("same attribute as one already measured")).length;
  const vague = rejected.length - thin - repeats;
  const kept = run.attribute_scores.filter((s) => s.discovered);
  const small = lim.some((l) => l.startsWith("Small sample"));
  const other = [
    ...discovery.filter((l) => !proposals.includes(l)).map((l) => l[0].toUpperCase() + l.slice(1)),
    ...lim.filter((l) => !l.startsWith(DROPPED) && !l.startsWith(DISCOVERY) && !l.startsWith("Small sample")
      && !/^\d+ of \d+ brand answers were excluded/.test(l)),
  ];
  const buyer = run.probes.filter((p) => p.kind === "blind" && p.phase === "baseline").length;
  const tries = d.tries ?? 1, sampled = d.repeat_sample ?? 0;
  const buyerAsks = buyer + sampled * (tries - 1);
  return (
    <section className="card checks-panel">
      <h3>How we checked this report</h3>
      <ul className="checks-list">
        <li>
          <strong>{d.n_named} of {d.named_asked}</strong> <Term k="brand_question">branded question</Term> answers
          counted{d.excluded_named > 0 && `; ${d.excluded_named} left out, explained above`}.
          {small && " That is a small sample, so treat a difference of a few points as noise."}
        </li>
        {buyer > 0 && (
          <li>
            <strong>{d.n_blind} of {buyerAsks}</strong> <Term k="buyer_question">unbranded question</Term> answers
            counted ({plural(buyer, "question")} asked once
            {sampled > 0 && `, ${sampled} of them ${tries} times over`}).
          </li>
        )}
        <Count summary={<>
          <strong>{dropped.length}</strong> {dropped.length === 1 ? "reading" : "readings"} of the AI’s answers thrown away
          {notVerbatim > 0 && <>, {notVerbatim} because the quote did not match the answer word for word</>}
          {cited > 0 && <>, {cited} because the quote came from a cited source, not the answer</>}
          {unknown > 0 && <>, {unknown} for naming a trait this run was not measuring</>}
          {otherDrop > 0 && <>, {otherDrop} for another reason</>}.
          {" "}Nothing is counted without a word-for-word quote.
        </>} items={dropped.map((l, i) => <DroppedLine key={i} text={l} run={run} />)} />
        {kept.length + rejected.length > 0 && (
          <Count summary={<>
            <strong>{kept.length + rejected.length}</strong> possible new traits suggested by reading the answers
            together; {kept.length} kept{kept.length > 0 && <> ({kept.map((s) => `“${s.label}”`).join(", ")})</>}
            {thin > 0 && <>, {thin} rejected for too little support</>}
            {repeats > 0 && <>, {repeats} rejected as repeats of a trait already measured</>}
            {vague > 0 && <>, {vague} rejected as too vague to tell apart from what is measured</>}.
          </>} items={proposals.map((l, i) => <DiscoveryLine key={i} text={l} run={run} />)} />
        )}
        {other.length > 0 && (
          <Count summary={<>{plural(other.length, "more caveat")} to keep in mind</>}
                 items={other.map((l, i) => <Linked key={i} text={l} run={run} />)} />
        )}
      </ul>
      <p className="muted" style={{ margin: 0 }}>
        Every step the workflow took is in the{" "}
        <button className="linky" onClick={() => downloadRun(run)}>full data download (JSON)</button>.
      </p>
    </section>
  );
}
