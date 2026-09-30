// "Can AI read your site?": the retrievability audit (audit.py) as a red/green checklist per claim,
// plus where else AI gets its facts. Plain fetches on the server, no model, so nothing here is
// simulated; every mark opens its reason in place. The same section sits in the report's "Why AI
// misses you" tab and, closed, on the onboarding claims step.
import { useState } from "react";
import type { AuditCheck, AuditStatus, Run, SiteAudit } from "./api";
import { GLOSSARY } from "./glossary";
import { day } from "./labels";
import { checkProblems } from "./quickwins";
import { Popover, Term } from "./popover";

const MARK: Record<AuditStatus, string> = { pass: "✓", fail: "✕", unknown: "?" };
const SAID: Record<AuditStatus, string> = { pass: "passes", fail: "fails", unknown: "could not check" };
/** Pill names; the glossary holds the full term and its definition. */
const SHORT: Record<AuditCheck["key"], string> = {
  crawlers: "AI crawlers", raw_text: "Text without JS", markup: "Structured data", headings: "Headings",
  speed: "Speed", llms_txt: "llms.txt", no_js: "Pages without JS",
};
const SOURCE_STATUS = { found: "pass", missing: "fail", not_checked: "unknown" } as const;
const SOURCE_SAID = { found: "found", missing: "not found", not_checked: "not checked" } as const;

/** Where a person can look by hand when the site links no profile: those sites turn automated checks away. */
const SEARCH: Record<string, string> = {
  Crunchbase: "https://www.crunchbase.com/textsearch?q=",
  G2: "https://www.g2.com/search?query=",
  LinkedIn: "https://www.linkedin.com/search/results/companies/?keywords=",
};

const path = (url: string) => {
  try { const p = new URL(url).pathname; return p === "/" ? "homepage" : p; } catch { return url; }
};

/** One plain sentence for the section header: what is in AI's way, and whether Wikidata knows you. */
function auditFinding(a: SiteAudit): string {
  const n = a.claims.length;
  const failing = a.claims.filter((c) => c.checks.some((k) => k.status === "fail")).length;
  const clean = a.claims.filter((c) => c.checks.every((k) => k.status === "pass")).length;
  const claims = n === 0 ? "No claim on your pages to check"
    : failing ? `${failing} of ${n} claim${n === 1 ? " has" : "s have"} something in AI’s way`
    : clean === n ? `AI can read all ${n} of your claims`
    : `${clean} of ${n} claims pass every check; the rest could not be checked`;
  const wd = a.entities.find((e) => e.source === "Wikidata")?.status;
  return claims + (wd === "missing" ? "; no Wikidata entry" : wd === "found" ? "; Wikidata knows you" : "");
}

function Check({ c, page, bare }: { c: AuditCheck; page?: string | null; bare?: boolean }) {
  const g = GLOSSARY[c.key];
  return (
    <Popover label={g.term} className={`check ${c.status}${bare ? " bare" : ""}`}
             trigger={<><span aria-hidden="true">{MARK[c.status]}</span>{bare ? <span className="sr-only">{SHORT[c.key]}</span> : SHORT[c.key]}
               <span className="sr-only">: {SAID[c.status]}</span></>}>
      <strong className="pop-title">{g.term}: {SAID[c.status]}</strong>
      <p>{c.detail}</p>
      {page && <p className="muted">Page checked: <a href={page} target="_blank" rel="noreferrer">{path(page)}</a></p>}
      <h4>What this checks</h4>
      <p className="muted">{g.def}</p>
    </Popover>
  );
}

function Source({ e, siteSays, name }: { e: SiteAudit["entities"][number]; siteSays?: string | null; name?: string }) {
  const search = !e.url && name && SEARCH[e.source] ? SEARCH[e.source] + encodeURIComponent(name) : null;
  const status = SOURCE_STATUS[e.status];
  return (
    <Popover label={e.source} className={`check ${status}`} wide={!!e.says}
             trigger={<><span aria-hidden="true">{e.status === "not_checked" ? "–" : MARK[status]}</span>{e.source}
               <span className="sr-only">: {SOURCE_SAID[e.status]}</span></>}>
      <strong className="pop-title">{e.source}: {SOURCE_SAID[e.status]}</strong>
      <p>{e.summary}</p>
      {e.says && <><h4>{e.source} says</h4><p className="quote">{e.says}</p></>}
      {e.says && siteSays && <><h4>Your site says</h4><p className="quote">{siteSays}</p></>}
      {e.url && <p><a href={e.url} target="_blank" rel="noreferrer">Open the {e.source} page</a></p>}
      {search && <p><a href={search} target="_blank" rel="noreferrer">Search {e.source} for {name}</a></p>}
    </Popover>
  );
}

/** Advice lines said once each, with how many claim pages they are for. */
const advice = (a: SiteAudit) => {
  const seen = new Map<string, number>();
  for (const c of a.claims) for (const line of c.advice ?? []) seen.set(line, (seen.get(line) ?? 0) + 1);
  return [...seen];
};

/** The body: problems first, then every mark in one grid (each still opens its reason), the whole
 * site, and where else AI gets its facts. */
function AuditBody({ audit, name, siteSays, recheck, busy }: {
  audit: SiteAudit | null; name?: string; siteSays?: string | null; recheck?: (() => void) | null; busy: boolean;
}) {
  if (!audit) {
    return (
      <>
        <p className="muted" style={{ margin: 0 }}>This company was read before this check existed.</p>
        {recheck && <p className="muted audit-foot"><button className="linky" disabled={busy} onClick={recheck}>{busy ? "Checking…" : "Check now"}</button></p>}
      </>
    );
  }
  const { failing, passing } = checkProblems(audit.claims);
  const keys = [...new Set(audit.claims.flatMap((c) => c.checks.map((k) => k.key)))];
  const n = audit.claims.length;
  return (
    <>
      <p style={{ margin: 0 }}>
        We read each page that states a claim the way AI crawlers do: plain HTML, no JavaScript. Problems first;
        tap a mark for its reason.
      </p>
      {n > 0 && (
        <ul className="audit-summary">
          {failing.map((f) => (
            <li key={f.key}><span className="mark-warn" aria-hidden="true">!</span> <Term k={f.key}>{GLOSSARY[f.key].term}</Term>: fails on {f.n} of {n} claim {n === 1 ? "page" : "pages"}.</li>
          ))}
          {audit.site.filter((k) => k.status === "fail").map((k) => (
            <li key={k.key}><span className="mark-warn" aria-hidden="true">!</span> <Term k={k.key}>{GLOSSARY[k.key].term}</Term>: {k.detail}</li>
          ))}
          {passing.length > 0 && (
            <li><span className="mark-ok" aria-hidden="true">✓</span> Passing on every claim page: {passing.map((k, i) => (
              <span key={k}>{i ? ", " : ""}<Term k={k}>{SHORT[k]}</Term></span>))}.</li>
          )}
        </ul>
      )}
      {advice(audit).map(([line, count]) => (
        <p key={line} style={{ margin: 0 }}><strong>Advice{count > 1 ? ` for ${count} pages` : ""}:</strong> {line}</p>
      ))}
      {n > 0 && (
        <div className="table-scroll">
          <table className="compact checkgrid">
            <thead><tr><th>Claim · page</th>{keys.map((k) => <th key={k}>{SHORT[k]}</th>)}</tr></thead>
            <tbody>
              {audit.claims.map((c) => (
                <tr key={c.attribute_id}>
                  <td><strong>{c.label}</strong>{c.page_url && <span className="audit-page">{path(c.page_url)}</span>}</td>
                  {keys.map((k) => {
                    const check = c.checks.find((x) => x.key === k);
                    return <td key={k}>{check ? <Check c={check} page={c.page_url} bare /> : "–"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="audit-rows">
        <div><strong>Whole site</strong></div>
        <div className="checks-row">{audit.site.map((k) => <Check key={k.key} c={k} />)}</div>
        <div><strong><Term k="fact_sources" /></strong></div>
        <div className="checks-row">{audit.entities.map((e) => <Source key={e.source} e={e} siteSays={siteSays} name={name} />)}</div>
      </div>
      <p className="muted audit-foot">
        Checked {day(audit.checked_at)} with plain web requests; no AI was asked, nothing is estimated.{" "}
        {recheck && <button className="linky" disabled={busy} onClick={recheck}>{busy ? "Checking…" : "Check again"}</button>}
      </p>
    </>
  );
}

/** The whole section. Folded (the claims step) it shows only its one-line finding; `flat` (a report
 * sub-tab) it is a titled section with everything showing. */
export function SiteReadability({ audit, name, siteSays, open, flat, onRecheck }: {
  audit: SiteAudit | null; name?: string; siteSays?: string | null; open?: boolean; flat?: boolean;
  onRecheck?: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recheck = onRecheck ? () => {
    setBusy(true); setError(null);
    onRecheck().catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  } : null;
  const body = (
    <>
      <AuditBody audit={audit} name={name} siteSays={siteSays} recheck={recheck} busy={busy} />
      {error && <div className="callout error">{error}</div>}
    </>
  );
  if (flat) {
    return (
      <section className="panel-sec audit">
        <div className="panel-sec-head">
          <h3>Can AI read your site?</h3>
          <span className="block-found">{audit ? auditFinding(audit) : "Not checked yet"}</span>
        </div>
        {body}
      </section>
    );
  }
  return (
    <details className="block audit" open={open}>
      <summary>
        <span className="block-title">Can AI read your site?</span>
        <span className="block-found">{audit ? auditFinding(audit) : "Not checked yet"}</span>
      </summary>
      <div className="block-body">{body}</div>
    </details>
  );
}

/** The report tab's diagnosis sections. */
export function WhyAIMisses({ run }: { run: Run }) {
  if (run.audit) {
    return <SiteReadability audit={run.audit} name={run.profile.name} siteSays={run.profile.positioning_points?.[0]?.text} flat />;
  }
  return (
    <section className="panel-sec audit">
      <div className="panel-sec-head">
        <h3>Can AI read your site?</h3>
        <span className="block-found">Not checked for this run</span>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        {run.mode === "demo_replay"
          ? "A sample run has no real site to read."
          : "This run was measured before the site check existed. Check the site again from the company’s claims step, then measure: the next run carries the result."}
      </p>
    </section>
  );
}
