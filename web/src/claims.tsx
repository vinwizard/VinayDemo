// The step between reading a site and measuring it: what their own pages claim, and which of those
// claims the customer actually wants to be known for. Every claim here came from GET /api/onboard.
import { useState } from "react";
import type { ClaimCheck, CompanyDetail } from "./api";
import { deleteAttribute, patchCompany } from "./api";
import { statedOn } from "./labels";
import { Term } from "./popover";

interface Added { label: string; description: string; weight: number }

// A claim typed into "add something your copy never states" is intended by construction — typing it
// IS the expression of intent — so it starts weighted and cannot be dragged to the zero that would
// drop it out of the report unseen. Changing your mind is the Remove button, not a slider position.
// Mirrors api.ADDED_MIN_WEIGHT / AddedAttribute.
const ADDED_DEFAULT_WEIGHT = 0.5;
export const ADDED_MIN_WEIGHT = 0.1;


const EMPTY_DRAFT: Added = { label: "", description: "", weight: ADDED_DEFAULT_WEIGHT };

/**
 * One control, two floors, and the floor encodes WHO AUTHORED the claim — it is not cosmetic.
 * An extracted claim keeps min 0 and its "not intended" label: the crawler found it, the company
 * never asserted it to us, and zero honestly means "I do not want to be known for this". A claim
 * the customer typed starts at ADDED_DEFAULT_WEIGHT and cannot go below ADDED_MIN_WEIGHT, because
 * typing it was itself the intent; it leaves by the Remove button, which is visible and deliberate,
 * never by a drag to zero that silently deletes the row from the report.
 */
export function Slider({ value, onChange, id, label, min = 0, disabled }: {
  value: number; onChange: (v: number) => void; id: string; label: string; min?: number;
  disabled?: boolean;
}) {
  return (
    <div className="slider">
      <input id={id} type="range" min={min} max={1} step={0.1} value={value} aria-label={label}
             disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
      <span className={value === 0 ? "muted" : "weight"}>
        {value === 0 ? "not intended" : `intent ${value.toFixed(1)}`}
      </span>
    </div>
  );
}

const weightsOf = (c: CompanyDetail) =>
  Object.fromEntries(c.attributes.map((a) => [a.id, a.intended_weight ?? 0]));

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/**
 * Quote validation, shown as the rigour it is rather than as errors: every claim appears once, under
 * its own label, in the one list that says what happened to it.
 */
function HowWeChecked({ checks }: { checks: ClaimCheck[] }) {
  const kept = checks.filter((c) => c.kept);
  const notFound = checks.filter((c) => !c.kept && c.not_found);
  const unchecked = checks.filter((c) => !c.kept && !c.not_found);
  const trimmed = kept.filter((c) => c.quotes_removed > 0);
  const removed = trimmed.reduce((n, c) => n + c.quotes_removed, 0);
  const left = notFound.length + unchecked.length;
  return (
    <div className="callout checks">
      <div className="row checks-head">
        <h4>How we checked these claims</h4>
        <span className="pill landed">{kept.length} verified</span>
        {left > 0 && <span className="pill neutral">{left} left out</span>}
      </div>
      <p className="muted">
        A claim is kept only if we can quote it word for word from your own site.
      </p>
      {notFound.length > 0 && (
        <details className="block" open>
          <summary><span className="block-title">Left out: we couldn't find them on your pages</span></summary>
          <ul className="block-body">{notFound.map((c, i) => <li key={i}>{c.label}</li>)}</ul>
        </details>
      )}
      {unchecked.length > 0 && (
        <details className="block" open>
          <summary><span className="block-title">Left out: found, but the claim could not be checked</span></summary>
          <ul className="block-body">
            {unchecked.map((c, i) => (
              <li key={i}>{c.label}{c.notes.length > 0 && <div className="muted">{c.notes.join(" ")}</div>}</li>
            ))}
          </ul>
        </details>
      )}
      {trimmed.length > 0 && (
        <details className="block">
          <summary><span className="block-title">Kept, with {plural(removed, "quote")} removed</span></summary>
          <ul className="block-body">
            {trimmed.map((c, i) => (
              <li key={i}>
                {c.label} <span className="muted">— {c.quotes_matched} of {c.quotes_matched + c.quotes_removed} quotes matched</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {left > 0 && (
        <p className="muted">Think one of these belongs? Add it above as your own claim.</p>
      )}
    </div>
  );
}

export function ClaimsStep({ company, running, onCompany, onMeasure }: {
  company: CompanyDetail;
  running: boolean;
  onCompany: (c: CompanyDetail) => void;
  onMeasure: (c: CompanyDetail) => void;
}) {
  // Weights start where the saved company left them, and at zero for a claim nobody has weighted.
  const [weights, setWeights] = useState<Record<string, number>>(() => weightsOf(company));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Added>(EMPTY_DRAFT);
  const [category, setCategory] = useState(company.profile.core_category ?? "");

  const load = (c: CompanyDetail) => {
    onCompany(c); setWeights(weightsOf(c)); setCategory(c.profile.core_category ?? "");
  };

  /** Saves intent, then optionally measures with the company the server just returned. */
  const save = (thenMeasure: boolean) => {
    if (company.replay) { if (thenMeasure) onMeasure(company); return; }
    setSaving(true); setError(null);
    const added = draft.label.trim()
      ? [{ label: draft.label.trim(), description: draft.description.trim() || null,
           intended_weight: draft.weight }]
      : [];
    const moved = category.trim() !== (company.profile.core_category ?? "");
    patchCompany(company.id, { weights, added, ...(moved ? { core_category: category.trim() } : {}) })
      .then((c) => {
        load(c); setSaved(true); setDraft(EMPTY_DRAFT);
        if (thenMeasure) onMeasure(c);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false));
  };

  /** A claim the customer typed leaves by an explicit deletion, never by being weighted to nothing. */
  const remove = (attributeId: string) => {
    setSaving(true); setError(null);
    deleteAttribute(company.id, attributeId)
      .then(load)
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false));
  };

  const intended = Object.values(weights).filter((w) => w > 0).length;
  const nothingToMeasure = !company.attributes.length && !draft.label.trim();
  const locked = saving || running;
  const fixed = locked || company.replay;

  return (
    <div className="stack">
      <p className="lede">
        Optional: move the slider on each claim you actually want to be known for. A slider left at
        zero stays at zero: we never guess an intention you did not state.
      </p>

      {!company.replay && (
        <div className="claim category">
          <div>
            <label className="claim-label" htmlFor={`cat-${company.id}`}>Core category</label> <Term k="core_category" icon />
            <p className="muted" style={{ margin: ".2rem 0 .5rem" }}>
              What a buyer shops for when they need {company.profile.name}: where you aim to be. Half
              the buyer questions ask about it; the other half ask about the category AI’s answers
              about {company.profile.name} already place it in, so the two show side by side. A
              control question asks AI for each category’s leading tools, so a low score can be
              checked. Read from your one-line description — correct it if it is wrong.
            </p>
            <input id={`cat-${company.id}`} placeholder="e.g. payroll software for startups" value={category}
                   maxLength={80} style={{ width: "100%" }} disabled={fixed}
                   onChange={(e) => { setCategory(e.target.value); setSaved(false); }} />
            <div className="muted" style={{ marginTop: ".3rem" }}>
              {!company.profile.core_category
                ? "No core category saved yet (this company was read before categories existed), so where you aim to be is not asked about. Type one and save to ask about it."
                : category.trim() !== company.profile.core_category
                ? "Save to write new buyer questions for this category."
                : `${plural(company.profile.category_questions?.length ?? 0, "buyer question")} ready for this category`}
            </div>
          </div>
        </div>
      )}

      <div className="claims">
        {company.attributes.map((a) => (
          <div key={a.id} className={`claim ${(weights[a.id] ?? 0) > 0 ? "on" : ""}`}>
            <div>
              <div className="claim-label">{a.label}</div>
              {a.description && <div className="desc">{a.description}</div>}
              <div className="muted">
                {company.replay
                  ? `bundled sample: stated on ${statedOn(a.claim_pages, a.claim_pages_total)} in the sample — authored, not read from a site`
                  : a.claim_pages_total
                  ? `stated on ${statedOn(a.claim_pages, a.claim_pages_total)}`
                  : "no page data"}
                {a.added_by_user && " · added by you"}
              </div>
              {a.claim_quotes[0] && (
                <p className="quote">
                  {company.replay && <span className="tag sample">sample</span>} {a.claim_quotes[0]}
                </p>
              )}
              {a.claim_quotes.length === 0 && (
                <p className="muted" style={{ margin: ".3rem 0 0" }}>
                  {company.replay && <span className="tag sample">sample</span>} {a.note ?? "No quote on their site states this."}
                </p>
              )}
            </div>
            <div className="stack" style={{ gap: ".3rem", alignItems: "flex-end" }}>
              <Slider id={`w-${company.id}-${a.id}`} label={`Intent for ${a.label}`}
                      value={weights[a.id] ?? 0} disabled={fixed}
                      min={a.added_by_user ? ADDED_MIN_WEIGHT : 0}
                      onChange={(v) => { setWeights((w) => ({ ...w, [a.id]: v })); setSaved(false); }} />
              {a.added_by_user && (
                <button className="linky" disabled={fixed}
                        onClick={() => remove(a.id)}>Remove this claim</button>
              )}
            </div>
          </div>
        ))}

        <div className="claim add">
          <div>
            <div className="claim-label">Add something your copy never states</div>
            <p className="muted" style={{ margin: ".2rem 0 .5rem" }}>
              A claim you want to be known for but do not make anywhere on those pages. It gets zero
              of {company.pages.length} pages, which is the finding, not missing data. Adding it is
              itself the intent, so it starts weighted and cannot be weighted away — drag the slider
              if it matters more or less, or remove it from its row once added if you change your mind.
            </p>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <input aria-label="Attribute" placeholder="e.g. Secure by default" value={draft.label}
                     disabled={fixed}
                     onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} />
              <input aria-label="What it means" placeholder="What that means, in one sentence"
                     value={draft.description} style={{ flex: "1 1 18rem" }} disabled={fixed}
                     onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
            </div>
          </div>
          <Slider id={`w-${company.id}-new`} label="Intent for the claim you are adding"
                  min={ADDED_MIN_WEIGHT} value={draft.weight} disabled={fixed}
                  onChange={(v) => setDraft((d) => ({ ...d, weight: v }))} />
        </div>
      </div>

      {company.checks.length > 0 && <HowWeChecked checks={company.checks} />}

      {company.warnings.length > 0 && (
        <div className="callout warn-box">
          <h4>Read this before you trust a number</h4>
          <ul>{company.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      {error && <div className="callout error">{error}</div>}

      <div className="actions">
        <span className="muted">
          {nothingToMeasure
            ? "Nothing on their site survived quote validation, so there is nothing to measure yet. Add a claim above to measure it."
            : intended === 0
            ? "Nothing weighted: measuring compares what your site claims with what AI says. Weights are optional."
            : `${intended} claim${intended === 1 ? "" : "s"} weighted${saved ? " · saved" : ""}`}
        </span>
        <div className="row">
          <button className="ghost" onClick={() => save(false)} disabled={fixed}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button className="primary" onClick={() => save(true)} disabled={locked || nothingToMeasure}
                  title={nothingToMeasure ? "Nothing on their site survived quote validation. Add a claim first." : ""}>
            {running ? "Measuring…" : `Measure ${company.profile.name}`}
          </button>
        </div>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        {company.replay
          ? "Replays the bundled sample's authored answers — no model is asked and nothing is paid."
          : <>Measuring asks a real AI model, with web search, every question below — about a minute of
            paid calls. It measures that model through its API at this moment, not the ChatGPT app.</>}
      </p>
    </div>
  );
}
