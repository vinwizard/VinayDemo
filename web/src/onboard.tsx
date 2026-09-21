// Screen 1 for a company that is not a bundled demo: a name, a website, and what their own pages
// actually claim. Everything here comes from GET /api/onboard, which has existed and worked for a
// while with nothing in the browser ever calling it.
import { useEffect, useState } from "react";
import type { CompanyDetail, CompanySummary } from "./api";
import { deleteAttribute, getCompanies, getCompany, onboard, patchCompany } from "./api";
import { statedOn } from "./labels";

interface Added { label: string; description: string; weight: number }

// A claim typed into "add something your copy never states" is intended by construction — typing it
// IS the expression of intent — so it starts weighted and cannot be dragged to the zero that would
// drop it out of the report unseen. Changing your mind is the Remove button, not a slider position.
// Mirrors api.ADDED_MIN_WEIGHT / AddedAttribute.
const ADDED_DEFAULT_WEIGHT = 0.5;
const ADDED_MIN_WEIGHT = 0.1;

/** Mirrors ana.MAX_TOPICS: the buyer axis is capped at four topics of three questions. */
const MAX_BUYER_TOPICS = 4;

/**
 * One control, two floors, and the floor encodes WHO AUTHORED the claim — it is not cosmetic.
 * An extracted claim keeps min 0 and its "not intended" label: the crawler found it, the company
 * never asserted it to us, and zero honestly means "I do not want to be known for this". A claim
 * the customer typed starts at ADDED_DEFAULT_WEIGHT and cannot go below ADDED_MIN_WEIGHT, because
 * typing it was itself the intent; it leaves by the Remove button, which is visible and deliberate,
 * never by a drag to zero that silently deletes the row from the report.
 */
function Slider({ value, onChange, id, min = 0 }: {
  value: number; onChange: (v: number) => void; id: string; min?: number;
}) {
  return (
    <div className="row" style={{ gap: ".5rem" }}>
      <input id={id} type="range" min={min} max={1} step={0.1} value={value}
             onChange={(e) => onChange(Number(e.target.value))} />
      <span className="muted" style={{ width: "5.5rem" }}>
        {value === 0 ? "not intended" : `intent ${value.toFixed(1)}`}
      </span>
    </div>
  );
}

export function Onboard({ liveAvailable, busy, onMeasure }: {
  liveAvailable: boolean;
  busy: boolean;
  onMeasure: (company: CompanyDetail) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState<Added>({ label: "", description: "", weight: ADDED_DEFAULT_WEIGHT });
  const [known, setKnown] = useState<CompanySummary[]>([]);

  const refresh = () => { getCompanies().then(setKnown).catch(() => {}); };
  useEffect(refresh, []);

  const load = (c: CompanyDetail) => {
    setCompany(c);
    // Weights start where the saved company left them, and at zero for a claim nobody has weighted.
    setWeights(Object.fromEntries(c.attributes.map((a) => [a.id, a.intended_weight ?? 0])));
    setSaved(false);
  };

  const read = () => {
    setReading(true); setError(null); setCompany(null);
    onboard(url, name).then(load).catch((e: Error) => setError(e.message)).finally(() => setReading(false));
  };

  const reopen = (id: string) => {
    setError(null);
    getCompany(id).then((c) => { load(c); setName(c.profile.name); setUrl(`https://${c.profile.domain}`); })
      .catch((e: Error) => setError(e.message));
  };

  /** Saves intent, then optionally measures with the company the server just returned. */
  const save = (thenMeasure: boolean) => {
    if (!company) return;
    setSaving(true); setError(null);
    const added = draft.label.trim()
      ? [{ label: draft.label.trim(), description: draft.description.trim() || null,
           intended_weight: draft.weight }]
      : [];
    patchCompany(company.id, { weights, added })
      .then((c) => {
        load(c); setSaved(true); setDraft({ label: "", description: "", weight: ADDED_DEFAULT_WEIGHT }); refresh();
        if (thenMeasure) onMeasure(c);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false));
  };

  /** A claim the customer typed leaves by an explicit deletion, never by being weighted to nothing. */
  const remove = (attributeId: string) => {
    if (!company) return;
    setSaving(true); setError(null);
    deleteAttribute(company.id, attributeId)
      .then((c) => { load(c); refresh(); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false));
  };

  const intended = Object.values(weights).filter((w) => w > 0).length;

  return (
    <div className="stack">
      <div className="card">
        <h3>Onboard a company</h3>
        <p className="muted" style={{ marginTop: ".3rem" }}>
          Give a name and a website. We read up to six of their own pages and keep a claim only when
          a verbatim quote on one of those pages states it.
        </p>
        <div className="row" style={{ flexWrap: "wrap", marginTop: ".6rem" }}>
          <input aria-label="Company name" placeholder="Company name" value={name}
                 onChange={(e) => setName(e.target.value)} disabled={reading} />
          <input aria-label="Website" placeholder="https://example.com" value={url}
                 onChange={(e) => setUrl(e.target.value)} disabled={reading} style={{ minWidth: "18rem" }} />
          <button className="primary" onClick={read} disabled={reading || !url.trim()}>
            {reading ? "Reading…" : "Read their site"}
          </button>
        </div>
        <p className="muted" style={{ marginBottom: 0, marginTop: ".7rem" }}>
          <strong>Measuring an onboarded company needs an API key.</strong> The two bundled demos
          replay authored answers; a real company has none, so its answers have to be asked for.
          {liveAvailable ? " A key is configured, so this will make paid calls."
                         : " No key is configured here, so you can onboard and set intent, but not measure."}
        </p>
        {known.length > 0 && (
          <p className="muted" style={{ marginBottom: 0 }}>
            Already onboarded:{" "}
            {known.map((c, i) => (
              <span key={c.id}>
                {i > 0 && " · "}
                <button className="linky" onClick={() => reopen(c.id)}>{c.name}</button>
                {" "}({c.pages} pages, {c.intended} weighted)
              </span>
            ))}
          </p>
        )}
      </div>

      {error && <div className="card" style={{ borderColor: "var(--lost)", color: "var(--lost)" }}>{error}</div>}

      {company && (
        <>
          <div className="card">
            <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <h3>{company.profile.name} — what their own pages claim</h3>
              <span className="muted">{company.pages.length} pages read · {company.attributes.length} claims kept</span>
            </div>
            {company.profile.one_liner && <p style={{ margin: ".4rem 0 0" }}>{company.profile.one_liner}</p>}
            <p className="muted" style={{ marginTop: ".5rem" }}>
              Move a slider for each claim you actually want to be known for. A slider left at zero
              stays at zero: we never guess an intention you did not state.
            </p>
            {intended > MAX_BUYER_TOPICS && (
              <p className="warn">
                Only the first {MAX_BUYER_TOPICS} weighted claims get buyer questions, so {intended - MAX_BUYER_TOPICS}{" "}
                of your {intended} will be measured on the brand axis alone.
              </p>
            )}
            <div className="stack" style={{ marginTop: ".7rem" }}>
              {company.attributes.map((a) => (
                <div key={a.id} className="claim">
                  <div>
                    <div><strong>{a.label}</strong></div>
                    {a.description && <div className="desc">{a.description}</div>}
                    <div className="muted">
                      {a.claim_pages_total
                        ? `stated on ${statedOn(a.claim_pages, a.claim_pages_total)}`
                        : "no page data"}
                    </div>
                    {a.claim_quotes[0] && <p className="quote">{a.claim_quotes[0]}</p>}
                    {a.claim_quotes.length === 0 && (
                      <p className="muted" style={{ marginBottom: 0 }}>{a.note ?? "No quote on their site states this."}</p>
                    )}
                  </div>
                  <div className="stack" style={{ gap: ".3rem" }}>
                    <Slider id={`w-${a.id}`} value={weights[a.id] ?? 0}
                            min={a.added_by_user ? ADDED_MIN_WEIGHT : 0}
                            onChange={(v) => { setWeights((w) => ({ ...w, [a.id]: v })); setSaved(false); }} />
                    {a.added_by_user && (
                      <button className="linky" disabled={saving}
                              onClick={() => remove(a.id)}>Remove this claim</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {company.warnings.length > 0 && (
            <div className="card" style={{ borderColor: "var(--lost)" }}>
              <h3 className="warn">Read this before you trust a number</h3>
              <ul className="muted" style={{ marginBottom: 0 }}>
                {company.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          <div className="card">
            <h3>Add something your copy never states</h3>
            <p className="muted" style={{ marginTop: ".3rem" }}>
              A claim you want to be known for but do not make anywhere on those pages. It gets zero
              of {company.pages.length} pages, which is the finding, not missing data. Adding it is
              itself the intent, so it starts weighted and cannot be weighted away — drag the slider
              if it matters more or less, or remove it from its row above if you change your mind.
            </p>
            <div className="row" style={{ flexWrap: "wrap", marginTop: ".5rem" }}>
              <input aria-label="Attribute" placeholder="e.g. Secure by default" value={draft.label}
                     onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} />
              <input aria-label="What it means" placeholder="What that means, in one sentence"
                     value={draft.description} style={{ minWidth: "20rem" }}
                     onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
              <Slider id="w-new" min={ADDED_MIN_WEIGHT} value={draft.weight}
                      onChange={(v) => setDraft((d) => ({ ...d, weight: v }))} />
            </div>
          </div>

          <div className="card row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
            <span className="muted">
              {intended === 0
                ? "Nothing is weighted yet, so there is no intended positioning to score against."
                : `${intended} claim${intended === 1 ? "" : "s"} weighted${saved ? " · saved" : ""}`}
            </span>
            <div className="row">
              <button className="ghost" onClick={() => save(false)} disabled={saving || busy}>
                {saving ? "Saving…" : "Save intent"}
              </button>
              <button className="primary" onClick={() => save(true)}
                      disabled={saving || busy || !liveAvailable}
                      title={liveAvailable ? "" : "Needs OPENAI_API_KEY"}>
                {busy ? "Measuring…" : `Measure ${company.profile.name}`}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
