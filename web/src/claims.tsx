// The step between reading a site and measuring it: what their own pages claim, and which of those
// claims the customer actually wants to be known for. Every claim here came from GET /api/onboard.
import { useState } from "react";
import type { ClaimCheck, CompanyDetail } from "./api";
import { deleteAttribute, patchCompany, reaudit } from "./api";
import { SiteReadability } from "./audit";
import { plural, statedOn } from "./labels";
import { intentWord } from "./quickwins";
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
  // The weight in words ("Top priority"), the number beside it for a screen reader and the report
  return (
    <div className="slider">
      <input id={id} type="range" min={min} max={1} step={0.1} value={value} aria-label={label}
             aria-valuetext={`${intentWord(value)} (${value.toFixed(1)})`}
             disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
      <span className={value === 0 ? "muted" : "weight"}>{intentWord(value)}</span>
    </div>
  );
}

const weightsOf = (c: CompanyDetail) =>
  Object.fromEntries(c.attributes.map((a) => [a.id, a.intended_weight ?? 0]));


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
    <div className="checks">
      <div className="row checks-head">
        <h4>How we checked these claims</h4>
        <span className="pill landed">{kept.length} verified</span>
        {left > 0 && <span className="pill neutral">{left} left out</span>}
      </div>
      <p style={{ margin: 0 }}>
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
  onMeasure: (c: CompanyDetail, fresh: boolean) => void;
}) {
  // Weights start where the saved company left them, and at zero for a claim nobody has weighted.
  const [weights, setWeights] = useState<Record<string, number>>(() => weightsOf(company));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Added>(EMPTY_DRAFT);
  const [category, setCategory] = useState(company.profile.core_category ?? "");
  const [fresh, setFresh] = useState(false);

  const load = (c: CompanyDetail) => {
    onCompany(c); setWeights(weightsOf(c)); setCategory(c.profile.core_category ?? "");
  };
  /** One change sent to the server: the form is locked while it runs, and a refusal is shown. */
  const act = (call: Promise<CompanyDetail>, then: (c: CompanyDetail) => void) => {
    setSaving(true); setError(null);
    call.then(then).catch((e: Error) => setError(e.message)).finally(() => setSaving(false));
  };

  /** Saves intent, then optionally measures with the company the server just returned. */
  const save = (thenMeasure: boolean) => {
    if (company.replay) { if (thenMeasure) onMeasure(company, false); return; }
    const added = draft.label.trim()
      ? [{ label: draft.label.trim(), description: draft.description.trim() || null,
           intended_weight: draft.weight }]
      : [];
    const moved = category.trim() !== (company.profile.core_category ?? "");
    act(patchCompany(company.id, { weights, added, ...(moved ? { core_category: category.trim() } : {}) }), (c) => {
      load(c); setSaved(true); setDraft(EMPTY_DRAFT);
      if (thenMeasure) onMeasure(c, fresh);
    });
  };

  /** A claim the customer typed leaves by an explicit deletion, never by being weighted to nothing. */
  const remove = (attributeId: string) => act(deleteAttribute(company.id, attributeId), load);

  /** A flagged claim reviewed: keep measuring it, or set it aside (and restore it later). */
  const review = (attributeId: string, decision: "keep" | "set_aside") =>
    act(patchCompany(company.id, { weights: {}, added: [], review: { [attributeId]: decision } }), onCompany);

  const intended = Object.values(weights).filter((w) => w > 0).length;
  const nothingToMeasure = !company.attributes.length && !draft.label.trim();
  const locked = saving || running;
  const fixed = locked || company.replay;

  const kept = company.checks.filter((c) => c.kept).length;
  const left = company.checks.length - kept;
  const where = company.profile.domain ? `${company.profile.name}'s own pages` : "your documents";
  const [firstNote, ...moreNotes] = company.warnings;
  return (
    <div className="stack claims-step">
      <section className="part" aria-labelledby={`p1-${company.id}`}>
        <h4 id={`p1-${company.id}`}><span className="partno" aria-hidden="true">1</span> Here’s what {where} say</h4>
        <p>
          {company.replay ? `${plural(company.attributes.length, "claim")}, authored for the bundled sample.`
            : <>We read {plural(company.pages.length, "page")} and found {plural(company.attributes.length, "claim")}.
              {" "}Every one is quoted word for word from those pages.</>}
        </p>
        {firstNote && (
          <div className="note-amber">
            {firstNote}
            {moreNotes.length > 0 && (
              <details>
                <summary>{plural(moreNotes.length, "more note")}</summary>
                <ul>{moreNotes.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </details>
            )}
          </div>
        )}
      </section>

      <section className="part" aria-labelledby={`p2-${company.id}`}>
        <h4 id={`p2-${company.id}`}><span className="partno" aria-hidden="true">2</span> Which of these do you want to be known for?</h4>
        <p>
          Slide each one to how much it matters to you. Leave it at <strong>Not a goal</strong> if it
          doesn’t: we never guess an intention you did not state. Optional.
        </p>
        <div className="claims">
          {company.attributes.map((a) => (
            <div key={a.id} className={`claim ${(weights[a.id] ?? 0) > 0 ? "on" : ""}${a.set_aside ? " aside" : ""}`}>
              <div>
                <div className="claim-label">{a.label}</div>
                {a.description && <div className="desc">{a.description}</div>}
                {a.claim_quotes[0] ? (
                  <details className="claim-quote">
                    <summary>
                      {company.replay
                        ? `bundled sample: stated on ${statedOn(a.claim_pages, a.claim_pages_total)} in the sample — authored, not read from a site`
                        : a.claim_pages_total ? `On ${a.claim_pages} of ${plural(a.claim_pages_total, "page")}` : "no page data"}
                      {a.added_by_user && " · added by you"}
                      {" · see the quote"}
                    </summary>
                    <p className="quote">
                      {company.replay && <span className="tag sample">sample</span>} {a.claim_quotes[0]}
                    </p>
                  </details>
                ) : (
                  <div className="muted">
                    {a.claim_pages_total ? `stated on ${statedOn(a.claim_pages, a.claim_pages_total)}` : "no page data"}
                    {a.added_by_user && " · added by you"}
                  </div>
                )}
                {(a.private_only || a.in_documents) && (
                  <div className="muted">{a.private_only ? <Term k="private_document" /> : "also in your documents"}</div>
                )}
                {a.set_aside ? (
                  <div className="review">
                    Set aside: kept on file, not measured.{" "}
                    <button className="linky" disabled={fixed} onClick={() => review(a.id, "keep")}>Restore it</button>
                  </div>
                ) : a.review && (
                  <div className="review">
                    <strong>Needs your review.</strong> {a.review}{" "}
                    <button className="linky" disabled={fixed} onClick={() => review(a.id, "keep")}>Keep it</button>
                    {" · "}
                    <button className="linky" disabled={fixed} onClick={() => review(a.id, "set_aside")}>Set it aside</button>
                  </div>
                )}
                {a.claim_quotes.length === 0 && (
                  <p className="muted" style={{ margin: ".3rem 0 0" }}>
                    {company.replay && <span className="tag sample">sample</span>} {a.note ?? "No quote on their site states this."}
                  </p>
                )}
              </div>
              <div className="stack" style={{ gap: ".3rem", alignItems: "stretch" }}>
                <Slider id={`w-${company.id}-${a.id}`} label={`How much ${a.label} matters`}
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
        </div>
        <details className="block add-claim" open={!company.attributes.length}>
          <summary><span className="block-title">+ Something you want to be known for that your pages never say</span></summary>
          <div className="block-body">
            <p style={{ margin: 0 }}>
              None of your {plural(company.pages.length, "page")} says it, and that is the finding, not missing data.{" "}
              <Term k="added_claim" icon />
            </p>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <input aria-label="Attribute" placeholder="e.g. Secure by default" value={draft.label}
                     disabled={fixed}
                     onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} />
              <input aria-label="What it means" placeholder="What that means, in one sentence"
                     value={draft.description} style={{ flex: "1 1 18rem" }} disabled={fixed}
                     onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
            </div>
            <Slider id={`w-${company.id}-new`} label="How much the claim you are adding matters"
                    min={ADDED_MIN_WEIGHT} value={draft.weight} disabled={fixed}
                    onChange={(v) => setDraft((d) => ({ ...d, weight: v }))} />
          </div>
        </details>
      </section>

      {!company.replay && (
        <section className="part" aria-labelledby={`p3-${company.id}`}>
          <h4 id={`p3-${company.id}`}><span className="partno" aria-hidden="true">3</span>
            <label htmlFor={`cat-${company.id}`}>What would a buyer call what you sell?</label></h4>
          <p>
            We ask AI the questions a buyer would type about this, without your name, to see if it brings
            you up: <Term k="where_aiming">where you aim to be</Term>.{" "}
            <Term k="core_category" icon note={<>Half the unbranded questions ask about it; the other half ask about the
              category AI’s answers about {company.profile.name} already place it in, so the two show side by side. A
              control question asks AI which companies lead each category, so a low score can be checked. Read from
              your one-line description — correct it if it is wrong.</>} />
          </p>
          <input id={`cat-${company.id}`} placeholder="e.g. payroll software for startups" value={category}
                 maxLength={80} style={{ width: "100%" }} disabled={fixed}
                 onChange={(e) => { setCategory(e.target.value); setSaved(false); }} />
          <div className="muted">
            {!company.profile.core_category
              ? "No core category saved yet (this company was read before categories existed), so where you aim to be is not asked about. Type one and save to ask about it."
              : category.trim() !== company.profile.core_category
              ? "Save to write new unbranded questions for this category."
              : `${plural(company.profile.category_questions?.length ?? 0, "unbranded question")} ready for “${company.profile.core_category}”`}
          </div>
        </section>
      )}

      {(company.checks.length > 0 || !company.replay) && (
        <details className="block">
          <summary>
            <span className="block-title">How we checked</span>
            <span className="block-found">
              {company.checks.length > 0 && `${kept} of ${company.checks.length} claims verified${left ? `, ${left} left out` : ""}`}
              {company.checks.length > 0 && !company.replay && " · "}
              {!company.replay && "Can AI read your site?"}
            </span>
          </summary>
          <div className="block-body">
            {company.checks.length > 0 && <HowWeChecked checks={company.checks} />}
            {!company.replay && (
              <SiteReadability audit={company.audit} name={company.profile.name} siteSays={company.profile.one_liner}
                               onRecheck={() => reaudit(company.id).then(onCompany)} />
            )}
          </div>
        </details>
      )}

      {error && <div className="callout error">{error}</div>}

      <div className="actions actionbar">
        <span>
          {nothingToMeasure
            ? "Nothing on their site survived quote validation, so there is nothing to measure yet. Add a claim above to measure it."
            : intended === 0
            ? "Nothing chosen: measuring compares what your site claims with what AI says. Choosing is optional."
            : `${plural(intended, "claim")} chosen${saved ? " · saved" : ""}`}
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
        <p className="muted actionbar-note">
          {company.replay
            ? "Replays the bundled sample's authored answers — no model is asked and nothing is paid."
            : <>Asks a real AI model, with web search, one to two minutes of paid calls. <Term k="measuring" icon />{" "}
              <label title="Ask every question again instead of reusing answers from the last 24 hours">
                <input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} /> Fresh run
              </label></>}
        </p>
      </div>
    </div>
  );
}
