// One popover for every "what is this?" on the report: zone chips, question references and the
// definitions of the terms this product invented. Hover opens it on a desktop, a tap pins it on a
// phone (where it is a bottom sheet), keyboard focus opens it and Enter pins it with focus inside,
// Esc closes it. It stays open while the pointer is inside, so its content can scroll and its links
// work. The panel is portalled to <body> so no card or sticky header clips it.
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, ReactNode } from "react";
import { GLOSSARY, type TermKey } from "./glossary";

export const PHONE = "(max-width: 600px)";
const GAP = 6;
const openStack: string[] = [];

export function Popover({ trigger, children, label, className = "", wide }: {
  trigger: ReactNode; children: ReactNode; label: string; className?: string; wide?: boolean;
}) {
  const id = useId();
  const btn = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const inside = useRef(false);
  const quiet = useRef(false);
  const timer = useRef<number>(undefined);
  const [open, setOpen] = useState<false | "peek" | "pinned">(false);
  const [pos, setPos] = useState<CSSProperties>({});

  const cancel = () => window.clearTimeout(timer.current);
  const peek = () => { cancel(); setOpen((o) => o || "peek"); };
  const leave = () => { cancel(); timer.current = window.setTimeout(() => setOpen((o) => (o === "peek" ? false : o)), 180); };
  const close = useCallback((refocus = false) => {
    window.clearTimeout(timer.current); setOpen(false);
    // Back to the trigger without the focus re-opening what was just closed.
    if (refocus) { quiet.current = true; btn.current?.focus(); quiet.current = false; }
  }, []);

  const place = useCallback(() => {
    const b = btn.current?.getBoundingClientRect();
    if (!b || window.matchMedia(PHONE).matches) { setPos({}); return; }
    const width = Math.min(wide ? 460 : 320, window.innerWidth - 16);
    const left = Math.max(8, Math.min(b.left, window.innerWidth - width - 8));
    const below = window.innerHeight - b.bottom - GAP - 8, above = b.top - GAP - 8;
    const up = below < 220 && above > below;
    setPos({ width, left, maxHeight: Math.min(440, up ? above : below),
             ...(up ? { bottom: window.innerHeight - b.top + GAP } : { top: b.bottom + GAP }) });
  }, [wide]);

  const shown = !!open;
  useLayoutEffect(() => { if (shown) place(); }, [shown, place]);
  useEffect(() => {
    if (!shown) return;
    openStack.push(id);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && openStack.at(-1) === id) close(true); };
    // A press inside this panel, or inside a popover opened from it, sets `inside` on the way down
    // (React delivers portal events through the component tree) before this listener runs.
    const onDown = (e: PointerEvent) => {
      if (!inside.current && !btn.current?.contains(e.target as Node)) close();
      inside.current = false;
    };
    const onMove = () => place();
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      openStack.splice(openStack.indexOf(id), 1);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  }, [shown, place, close, id]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <>
      <button ref={btn} type="button" className={`pop-trigger ${className}`} aria-expanded={!!open}
              aria-controls={open ? id : undefined} aria-haspopup="dialog"
              onMouseEnter={peek} onMouseLeave={leave}
              onFocus={(e) => { if (!quiet.current && e.currentTarget.matches(":focus-visible")) peek(); }}
              onBlur={(e) => { if (open === "peek" && !panel.current?.contains(e.relatedTarget as Node)) close(); }}
              onClick={(e) => {
                if (open === "pinned") { close(); return; }
                setOpen("pinned");
                // Enter or Space: take the keyboard into the panel so its links are reachable.
                if (e.detail === 0) requestAnimationFrame(() => panel.current?.focus());
              }}>
        {trigger}
      </button>
      {open && createPortal(
        <div ref={panel} id={id} role="dialog" aria-label={label} tabIndex={-1}
             className={`popover ${wide ? "wide" : ""}`} style={pos}
             onMouseEnter={peek} onMouseLeave={leave}
             onPointerDownCapture={() => { inside.current = true; }}
             onFocus={() => setOpen("pinned")}>
          <button type="button" className="pop-close" aria-label="Close" onClick={() => close(true)}>✕</button>
          {children}
        </div>,
        document.body,
      )}
    </>
  );
}

/**
 * A term this product invented, with its plain-English definition one hover or tap away. `icon`
 * renders a small ⓘ instead of underlining text, for a term that sits inside a computed sentence.
 */
export function Term({ k, children, icon, note }: { k: TermKey; children?: ReactNode; icon?: boolean; note?: ReactNode }) {
  const g = GLOSSARY[k];
  return (
    <Popover label={g.term} className={icon ? "term-icon" : "term"}
             trigger={icon ? <>ⓘ<span className="sr-only">What is {g.term}?</span></> : children ?? g.term}>
      <strong className="pop-title">{g.term}</strong>
      <p>{g.def}</p>
      {note && <p className="muted">{note}</p>}
    </Popover>
  );
}
