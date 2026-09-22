// "Can AI read your site?": the retrievability audit (audit.py) as a red/green checklist per claim,
// plus where else AI gets its facts. Plain fetches on the server, no model, so nothing here is
// simulated; every mark opens its reason in place. The same section sits in the report's "Why AI
// misses you" tab and, closed, on the onboarding claims step.
import { useState } from "react";
import type { AuditCheck, AuditStatus, Run, SiteAudit } from "./api";
import { GLOSSARY } from "./glossary";
import { day } from "./labels";
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

function Check({ c, page }: { c: AuditCheck; page?: string | null }) {
  const g = GLOSSARY[c.key];
  return (
    <Popover label={g.term} className={`check ${c.status}`}
             trigger={<><span aria-hidden="true">{MARK[c.status]}</span>{SHORT[c.key]}
               <span className="sr-only">: {SAID[c.status]}</span></>}>
      <strong className="pop-title">{g.term}: {SAID[c.status]}</strong>
      <p>{c.detail}</p>
      {page && <p className="muted">Page checked: <a href={page} target="_blank" rel="noreferrer">{path(page)}</a></p>}
      <h4>What this checks</h4>
      <p className="muted">{g.def}</p>
    </Popover>
  );
}

/** A claim with nothing in AI's way reads as one green mark; each check's reason is still one tap away. */
function AllPass({ checks, page }: { checks: AuditCheck[]; page?: string | null }) {
  return (
    <Popover label="Every check passes" className="check pass"
             trigger={<><span aria-hidden="true">✓</span>All {checks.length} checks pass</>}>
      <strong className="pop-title">Nothing in AI’s way</strong>
      {checks.map((k) => <p key={k.key}><strong>{GLOSSARY[k.key].term}.</strong> {k.detail}</p>)}
      {page && <p className="muted">Page checked: <a href={page} target="_blank" rel="noreferrer">{path(page)}</a></p>}
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

/** The whole section. `open` false shows only the header sentence: details are one tap away. */
export function SiteReadability({ audit, name, siteSays, open, onRecheck }: {
  audit: SiteAudit | null; name?: string; siteSays?: string | null; open?: boolean; onRecheck?: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recheck = onRecheck && (() => {
    setBusy(true); setError(null);
    onRecheck().catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  });
  return (
    <details className="block audit" open={open}>
      <summary>
        <span className="block-title">Can AI read your site?</span>
        <span className="block-found">{audit ? auditFinding(audit) : "Not checked yet"}</span>
      </summary>
      <div className="block-body">
        {audit ? (
          <>
            <p className="muted" style={{ margin: 0 }}>
              We read each page that states a claim the way AI crawlers do: plain HTML, no JavaScript.
              Tap a mark for the reason.
            </p>
            <ul className="audit-rows">
              {audit.claims.map((c) => (
                <li key={c.attribute_id}>
                  <div><strong>{c.label}</strong>{c.page_url && <span className="audit-page">{path(c.page_url)}</span>}</div>
                  <div className="checks-row">
                    {c.checks.every((k) => k.status === "pass") ? <AllPass checks={c.checks} page={c.page_url} />
                      : c.checks.map((k) => <Check key={k.key} c={k} page={c.page_url} />)}
                  </div>
                  {c.advice?.length ? <ul className="audit-advice">{c.advice.map((a) => <li key={a}>{a}</li>)}</ul> : null}
                </li>
              ))}
              <li>
                <div><strong>Whole site</strong></div>
                <div className="checks-row">{audit.site.map((k) => <Check key={k.key} c={k} />)}</div>
              </li>
              <li>
                <div><strong><Term k="fact_sources" /></strong></div>
                <div className="checks-row">{audit.entities.map((e) => <Source key={e.source} e={e} siteSays={siteSays} name={name} />)}</div>
              </li>
            </ul>
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            This company was read before this check existed.
          </p>
        )}
        <p className="muted audit-foot">
          {audit && <>Checked {day(audit.checked_at)} with plain web requests; no AI was asked, nothing is estimated. </>}
          {recheck && <button className="linky" disabled={busy} onClick={recheck}>{busy ? "Checking…" : audit ? "Check again" : "Check now"}</button>}
        </p>
        {error && <div className="callout error">{error}</div>}
      </div>
    </details>
  );
}

const phone = () => window.matchMedia("(max-width: 600px)").matches;

/** The report tab's diagnosis sections. */
export function WhyAIMisses({ run }: { run: Run }) {
  if (run.audit) {
    return <SiteReadability audit={run.audit} name={run.profile.name} siteSays={run.profile.positioning_points?.[0]?.text} open={!phone()} />;
  }
  return (
    <details className="block audit">
      <summary>
        <span className="block-title">Can AI read your site?</span>
        <span className="block-found">Not checked for this run</span>
      </summary>
      <div className="block-body">
        <p className="muted" style={{ margin: 0 }}>
          {run.mode === "demo_replay"
            ? "A sample run has no real site to read."
            : "This run was measured before the site check existed. Check the site again from the company’s claims step, then measure: the next run carries the result."}
        </p>
      </div>
    </details>
  );
}
