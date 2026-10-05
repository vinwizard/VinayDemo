import { useState } from "react";
import type { ReactNode } from "react";

/** Deterministic hue per name, so a company keeps its colour on every screen. */
const hue = (name: string) => [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

/**
 * The company's own website icon, captured at onboarding. When there is none, or it fails to load
 * (offline, moved, blocked), the first letter in a coloured square stands in — never a third-party
 * logo service.
 */
export function Logo({ name, url, size = 40 }: { name: string; url?: string | null; size?: number }) {
  const [failed, setFailed] = useState<string | null>(null);
  const style = { width: size, height: size, fontSize: size * 0.5 };
  if (url && failed !== url) {
    return <img className="logo" src={url} alt="" style={style} referrerPolicy="no-referrer"
                onError={() => setFailed(url)} />;
  }
  return (
    <span className="logo letter" aria-hidden style={{ ...style, background: `hsl(${hue(name)} 55% 45%)` }}>
      {(name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}

/** A collapsible section whose header already says what it found, so a closed page still reads. */
export function Block({ title, found, children, open, className = "" }: {
  title: ReactNode; found: ReactNode; children: ReactNode; open?: boolean; className?: string;
}) {
  return (
    <details className={`block ${className}`} open={open}>
      <summary>
        <span className="block-title">{title}</span>
        <span className="block-found">{found}</span>
      </summary>
      <div className="block-body">{children}</div>
    </details>
  );
}

/** One titled part of a report tab, headed by what it found. */
export function Section({ title, found, children, className }: {
  title: ReactNode; found: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={className ? `panel-sec ${className}` : "panel-sec"}>
      <div className="panel-sec-head">
        <h3>{title}</h3>
        <span className="block-found">{found}</span>
      </div>
      {children}
    </section>
  );
}

/** One result block on the Results page: a title, the figure, and anything more one hover or tap away.
 * `sample` tags authored data where it appears, beside the page's banner. */
export function Tile({ title, children, wide, sample, tour }: {
  title: ReactNode; children: ReactNode; wide?: boolean; sample?: boolean;
  /** The first-visit tour's anchor for this block (guide.tsx). */
  tour?: string;
}) {
  return (
    <section className={wide ? "tile wide" : "tile"} data-tour={tour}>
      <h3 className="tile-title">{title}{sample && <span className="tag sample">sample</span>}</h3>
      {children}
    </section>
  );
}

export const READ_ONLY_NOTE = "This live example is read-only: measure your own brand to investigate it.";
export const SAMPLE_NOTE = "Authored sample data, not a measurement: a live run fills this from the model's own answers.";
