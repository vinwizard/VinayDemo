import type { Answer, ReadStep } from "./api";
import { plural } from "./labels";
import { Term } from "./popover";

const host = (u?: string | null) => (u ?? "").replace(/^https?:\/\/(www\.)?/, "").split("/")[0];

/** The page's words, without the stamps and headers the search tool put in front of them. */
const pageText = (t: string) => t
  .replace(/^(?:(?:Published|Crawled|Content type|Source): [^;\n]*;\s*)+/, "")
  .replace(/^Total lines: \d+\s*/, "")
  .replace(/^L\d+: /gm, "")
  .trim();

const STEP: Record<ReadStep["kind"], string> = { search: "Searched", open_page: "Opened", find_in_page: "Looked up" };


/**
 * What the answering model read before it answered, in order: each search and the snippets it
 * returned, each page it opened and the lines it looked up in one. Recorded from the live call itself
 * (providers/live.reading_of), so it is the model's own reading list, not a reconstruction.
 */
export function WhatItRead({ a }: { a?: Answer }) {
  const steps = a?.trace;
  if (!steps?.length) return null;
  const searches = steps.filter((s) => s.kind === "search").length;
  const opened = steps.filter((s) => s.kind === "open_page").length;
  const results = steps.reduce((n, s) => n + s.results.length, 0);
  return (
    <details className="read">
      <summary>
        What AI read · {plural(searches, "search", "searches")}, {plural(results, "result")}
        {opened > 0 && `, ${plural(opened, "page")} opened`}
      </summary>
      <p className="muted">
        <Term k="what_ai_read" icon /> Everything the model was handed before it wrote this answer, as the
        search tool returned it. Page text is shortened here.
      </p>
      <ol className="read-steps">
        {steps.map((s, i) => (
          <li key={i}>
            <span className="read-kind">{STEP[s.kind]}</span>{" "}
            {s.kind === "search" ? s.queries.map((q) => `“${q}”`).join(", ")
              : <>{host(s.url)}{s.pattern && <> for “{s.pattern}”</>}</>}
            {s.results.length > 0 && (
              <ul className="read-results">
                {s.results.map((r, j) => (
                  <li key={j}>
                    <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title || host(r.url)}</a>
                    <span className="muted"> · {host(r.url)}{r.crawled && ` · crawled ${r.crawled}`}</span>
                    <span className="read-text">{pageText(r.text)}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
}
