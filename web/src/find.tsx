// Stage 1: which company, from its name alone. One web search offers up to three companies the name
// could mean, and the customer always confirms before anything is read: asked about a name no
// company has, the search still comes back with confident near-misses. A website typed here skips
// the search. Documents can be added to what is read, or read instead when there is no usable site.
import { useState } from "react";
import type { Found, Source, UploadedDoc } from "./api";
import { findCompany, uploadDocument } from "./api";
import { Term } from "./popover";

export interface ReadRequest { url: string; name: string; docs: UploadedDoc[]; onlyDocs: boolean }

type Mode = "name" | "finding" | "confirm" | "hint";

export function FindCompany({ busy, onRead }: { busy: boolean; onRead: (r: ReadRequest) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [hint, setHint] = useState("");
  const [mode, setMode] = useState<Mode>("name");
  const [found, setFound] = useState<Found | null>(null);
  const [pick, setPick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [docs, setDocs] = useState<UploadedDoc[]>([]);
  const [docErrors, setDocErrors] = useState<string[]>([]);
  const [uploading, setUploading] = useState(0);
  const [paste, setPaste] = useState("");
  const [onlyDocs, setOnlyDocs] = useState(false);
  const [showDocs, setShowDocs] = useState(false);

  const find = (more?: string) => {
    setMode("finding"); setError(null);
    findCompany(name.trim(), more)
      .then((f) => { setFound(f); setPick(0); setMode("confirm"); })
      .catch((e: Error) => { setError(e.message); setMode("name"); });
  };
  const upload = (all: { body: Blob; name: string }[]) => {
    const files = all.slice(0, Math.max(0, 5 - docs.length - uploading));
    if (files.length < all.length)
      setDocErrors((es) => [...es, `${all.length - files.length} file(s) not added: at most 5 documents.`]);
    setUploading((n) => n + files.length);
    for (const f of files) {
      uploadDocument(f.body, f.name)
        .then((d) => setDocs((ds) => [...ds, d]))
        .catch((e: Error) => setDocErrors((es) => [...es, e.message]))
        .finally(() => setUploading((n) => n - 1));
    }
  };
  const chosen = found?.candidates[pick];
  const read = (site: string) =>
    onRead({ url: site, name: name.trim() || chosen?.name || "", docs, onlyDocs: !!site && onlyDocs && docs.length > 0 });
  const site = mode === "confirm" && chosen ? `https://${chosen.domain}` : url.trim();
  const many = (found?.candidates.length ?? 0) > 1;

  const docsPanel = (
    <div className="docs card">
      <h3>Documents about the company</h3>
      <p className="muted" style={{ margin: 0 }}>
        PDF, Word (.docx), text or Markdown, up to 5 files of 10 MB each, or paste the words. Only the text
        is kept, and only you can see it. A claim is kept only when a quote in them states it word for word.
      </p>
      <input type="file" aria-label="Upload documents" multiple accept=".pdf,.docx,.txt,.md,.markdown"
             disabled={busy || docs.length >= 5}
             onChange={(e) => { upload([...(e.target.files ?? [])].map((f) => ({ body: f, name: f.name }))); e.target.value = ""; }} />
      <textarea aria-label="Paste a positioning statement" rows={3} value={paste} disabled={busy}
                placeholder="Or paste what the company does, for whom, and why it is different"
                onChange={(e) => setPaste(e.target.value)} />
      <div className="row">
        <button className="ghost" disabled={busy || !paste.trim() || docs.length >= 5}
                onClick={() => { upload([{ body: new Blob([paste], { type: "text/plain" }), name: "Pasted text.txt" }]); setPaste(""); }}>
          Add this text
        </button>
        {uploading > 0 && <span className="muted working">Reading {uploading} file{uploading > 1 ? "s" : ""}…</span>}
      </div>
      {docs.length > 0 && (
        <ul className="sources">
          {docs.map((d) => (
            <li key={d.id}>
              <span className="tag ok">Read</span> {d.filename} <span className="muted">· {d.chars.toLocaleString()} characters</span>{" "}
              <button className="linky" disabled={busy} onClick={() => setDocs((ds) => ds.filter((x) => x.id !== d.id))}>remove</button>
            </li>
          ))}
        </ul>
      )}
      {docErrors.map((e, i) => <div key={i} className="callout error">{e}</div>)}
      {docs.length > 0 && (
        <p className="muted" style={{ margin: 0 }}>
          A claim found only here is marked <Term k="private_document" />: AI cannot read a private file.
        </p>
      )}
      {docs.length > 0 && site && (
        <label className="row muted" style={{ margin: 0 }}>
          <input type="checkbox" checked={onlyDocs} onChange={(e) => setOnlyDocs(e.target.checked)} />
          Use only my documents (do not read the website)
        </label>
      )}
      {!site && (
        <div className="row" style={{ flexWrap: "wrap" }}>
          <button className="primary" onClick={() => read("")} disabled={busy || !docs.length || !name.trim() || uploading > 0}>
            Read my documents
          </button>
          {!name.trim() && <span className="muted">Type the company’s name above first.</span>}
        </div>
      )}
    </div>
  );

  return (
    <div className="stack">
      {(mode === "name" || mode === "finding") && (
        <>
          <p className="lede">
            Type the company’s name. We search the web for its own site and pages, and you confirm it is the
            right company before anything is read.
          </p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <input aria-label="Company name" placeholder="Perplexity" value={name} style={{ flex: "1 1 14rem" }}
                   onChange={(e) => setName(e.target.value)} disabled={busy || mode === "finding"}
                   onKeyDown={(e) => { if (e.key === "Enter" && name.trim() && !busy) find(); }} />
            <button className="primary" onClick={() => find()} disabled={busy || mode === "finding" || !name.trim()}>
              {mode === "finding" ? "Searching…" : "Find it"}
            </button>
          </div>
          {mode === "finding" && <p className="muted working" style={{ margin: 0 }}>Searching the web for “{name.trim()}”. This usually takes about 10 seconds.</p>}
          <details>
            <summary className="muted">I know the website</summary>
            <div className="row" style={{ flexWrap: "wrap", marginTop: ".5rem" }}>
              <input aria-label="Website" placeholder="perplexity.ai" value={url} style={{ flex: "1 1 16rem" }}
                     onChange={(e) => setUrl(e.target.value)} disabled={busy}
                     onKeyDown={(e) => { if (e.key === "Enter" && url.trim() && !busy) read(url.trim()); }} />
              <button className="ghost" onClick={() => read(url.trim())} disabled={busy || !url.trim() || uploading > 0}>
                Read this site
              </button>
            </div>
          </details>
          {error && <div className="callout error">{error}</div>}
          {!showDocs && !docs.length && (
            <button className="linky back" onClick={() => setShowDocs(true)}>No usable website? Upload documents instead</button>
          )}
        </>
      )}

      {mode === "confirm" && found && (
        found.candidates.length === 0 ? (
          <div className="callout error">
            We couldn’t find a company called “{name.trim()}”. Check the spelling, give us its website, or upload
            documents about it instead.{" "}
            <button className="linky" onClick={() => setMode("name")}>Try again</button>
          </div>
        ) : (
          <div className="stack">
            <h3 style={{ margin: 0 }}>
              {many ? `Several companies could be “${name.trim()}”. Which one is it?` : "Is this the company?"}
            </h3>
            {!found.exact && (
              <div className="callout warn-box">
                We found no company called exactly “{name.trim()}”. These have a similar name: pick one only if
                it really is the company you mean.
              </div>
            )}
            {found.candidates.map((c, i) => (
              <label key={c.domain} className={`cand${i === pick ? " sel" : ""}`}>
                {many && <input type="radio" name="candidate" checked={i === pick} onChange={() => setPick(i)} />}
                <span>
                  <strong>{c.name}</strong> · {c.domain}
                  {c.what && <><br /><span className="muted">{c.what}</span></>}
                </span>
              </label>
            ))}
            <div className="row" style={{ flexWrap: "wrap" }}>
              <button className="primary" disabled={busy || uploading > 0} onClick={() => read(site)}>
                {many || !found.exact ? "Yes, this one" : "Yes, that’s us"}
              </button>
              <button className="ghost" disabled={busy} onClick={() => setMode("hint")}>
                No, it’s a different company
              </button>
              {!showDocs && (
                <button className="linky" disabled={busy} onClick={() => setShowDocs(true)}>Add documents too</button>
              )}
            </div>
            <p className="muted" style={{ margin: 0 }}>
              If its site turns automated readers away, we use the <Term k="search_copy">search copies</Term> of
              its own pages instead.
            </p>
          </div>
        )
      )}

      {mode === "hint" && (
        <div className="stack">
          <label className="claim-label" htmlFor="find-hint">Tell us a little more: its website, or what it does</label>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <input id="find-hint" value={hint} style={{ flex: "1 1 18rem" }} placeholder="e.g. mercury.com, or “the business bank”"
                   onChange={(e) => setHint(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter" && hint.trim()) find(hint.trim()); }} />
            <button className="primary" disabled={!hint.trim()} onClick={() => find(hint.trim())}>Search again</button>
            <button className="linky" onClick={() => setMode("name")}>Back</button>
          </div>
        </div>
      )}

      {(showDocs || docs.length > 0) && mode !== "finding" && docsPanel}
    </div>
  );
}

const KIND: Record<string, [string, string]> = {
  page_fetch: ["ok", "Read from the site"],
  search_copy: ["info", "Search copy"],
  uploaded_document: ["ok", "Your document"],
};

/** What onboarding read, each with how it was read. */
export function SourceList({ sources, third }: { sources: Source[]; third?: { url: string; title: string | null }[] }) {
  const bare = (u: string) => u.replace(/^https?:\/\//, "");
  return (
    <div className="stack">
      <ul className="sources">
        {sources.map((s, i) => {
          const [tone, label] = KIND[s.kind] ?? ["ok", s.kind];
          return (
            <li key={`${s.url ?? s.title}-${i}`}>
              <span className={`tag ${tone}`}>{label}</span>{" "}
              {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{bare(s.url)}</a> : s.title}
              {s.kind === "search_copy" && (
                <span className="muted">{s.saved && ` · saved ${s.saved}`} <Term k="search_copy" icon /></span>
              )}
            </li>
          );
        })}
      </ul>
      {third && third.length > 0 && (
        <div>
          <p className="muted" style={{ margin: "0 0 .3rem" }}><Term k="third_party" />: not read for claims.</p>
          <ul className="sources">
            {third.map((t) => (
              <li key={t.url}><span className="tag third">Not counted</span> <a href={t.url} target="_blank" rel="noreferrer">{bare(t.url)}</a></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
