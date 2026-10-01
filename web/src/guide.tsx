// The first-visit guide on screen: the "how it works" story. Copy, memory and what the story shows
// live in tour.ts; definitions come from glossary.ts through the same Term popover the report uses.
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { Term } from "./popover";
import type { Story } from "./tour";
import { autoStarts, fill, markSeen, sceneMs, STORY_HEADLINES, STORY_WELCOME } from "./tour";

const store = (() => { try { return window.localStorage; } catch { return null; } })();
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
type Vars = { today?: number | null; potential?: number | null };

/** Tab stays inside the guide's dialog while it is open. */
function trapTab(e: ReactKeyboardEvent<HTMLElement>) {
  if (e.key !== "Tab") return;
  const f = [...e.currentTarget.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]")];
  if (!f.length) return;
  const [first, last] = [f[0], f[f.length - 1]];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

// ------------------------------------------------------------------------------------------ story

function StoryDialog({ story, vars, onSkip, onSee }: { story: Story | null; vars: Vars; onSkip: () => void; onSee: () => void }) {
  const still = reduced();
  const [scene, setScene] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hover, setHover] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const see = useRef<HTMLButtonElement>(null);
  const skip = useRef<HTMLButtonElement>(null);
  const brand = story?.brand;
  // Without a story (a pass holder) the welcome is the only scene.
  const LAST = story ? 4 : 0;   // the fix scene; the welcome is scene 0
  const go = (i: number) => { setScene(Math.max(0, Math.min(LAST, i))); setElapsed(0); };

  useEffect(() => { skip.current?.focus(); }, []);
  useEffect(() => {
    if (still || paused || hover || scene === LAST) return;
    const t0 = performance.now() - elapsed;
    let raf = 0;
    const tick = (now: number) => {
      const e = now - t0;
      if (e >= sceneMs(scene)) { setScene((s) => s + 1); setElapsed(0); return; }
      setElapsed(e); raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // `elapsed` only seeds a resumed scene; re-running on every frame would restart the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, paused, hover, still]);
  useEffect(() => { if (scene === LAST && !still) see.current?.focus(); }, [scene, still, LAST]);

  const onKey = (e: ReactKeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape" && !document.querySelector(".popover")) { e.preventDefault(); onSkip(); }
    else if (!still && e.key === "ArrowRight") { e.preventDefault(); go(scene + 1); }
    else if (!still && e.key === "ArrowLeft") { e.preventDefault(); go(scene - 1); }
    else trapTab(e);
  };

  const scenes: ReactNode[] = [
    <>
      <span className="story-kicker accent">Welcome</span>
      <h3 className="story-hello">{STORY_WELCOME.headline}</h3>
      <p className="story-lead">{STORY_WELCOME.lead}</p>
      <p>{STORY_WELCOME.body}</p>
      <p className="story-note">Inspired by <a href={STORY_WELCOME.creditUrl} target="_blank" rel="noopener noreferrer">Profound</a>.</p>
    </>,
    ...(story ? [<>
      <span className="story-kicker landed">1 · What they claim</span>
      <h3>{fill(STORY_HEADLINES[0], { brand })}</h3>
      <div className="story-page"><div className="story-url">{story.domain}</div>
        <p><mark>{story.claim}</mark></p></div>
      <p className="story-note">Word for word from {brand}’s own site, read when the company was onboarded.</p>
    </>,
    <>
      <span className="story-kicker accent">2 · What AI says</span>
      <h3>{fill(STORY_HEADLINES[1], { brand })}</h3>
      <div className="story-chat">
        <p className="story-q">{story.question}</p>
        <p className="story-a">{story.pieces.map((p, i) => (
          <span key={i}>…{i === story.identityPiece ? <strong>{p}</strong> : p}{i === story.pieces.length - 1 ? "…" : " "}</span>
        ))}</p>
      </div>
      <p className="story-note">
        Measured live{story.collected ? ` on ${story.collected}` : ""}: {story.model ?? "the measured model"} with
        web search, each question in a fresh chat. Word for word from its answer.
      </p>
    </>,
    <>
      <span className="story-kicker lost">3 · The gap</span>
      <h3>{STORY_HEADLINES[2]}</h3>
      <p>AI repeats <strong>{vars.today}%</strong> of what {brand} wants to be known for.</p>
      <div className="story-bar" aria-hidden><i style={{ "--w": `${vars.today}%` } as CSSProperties} /></div>
      <p className="story-big"><span>{vars.potential}%</span> <Term k="untapped_potential">untapped potential</Term></p>
      {story.identity && (
        <p className="story-chip"><span className="dot" />“{story.identity}”: AI says it, {brand} never did
          · <Term k="imposed">identity to shape</Term></p>
      )}
    </>,
    <>
      <span className="story-kicker winback">4 · The fix</span>
      <h3>{STORY_HEADLINES[3]}</h3>
      <p className="muted story-small">{story.fixPage.replace(/^https?:\/\/(www\.)?/, "")}: {story.fixBefore ? "replace" : "add"}</p>
      {story.fixBefore && <p className="story-old">{story.fixBefore}</p>}
      <p className="story-new"><strong>Suggested rewrite:</strong> {story.fixAfter}</p>
      <p className="story-note">A draft from the report’s <Term k="quick_wins">Quick wins</Term>: check it against the product before publishing.</p>
    </>] : []),
  ];

  return createPortal(
    <div className="guide-backdrop">
      <div className={`story${still ? " still" : ""}`} role="dialog" aria-modal="true" aria-label={brand ? `How Off Message works, shown on ${brand}` : "Welcome to Off Message"}
           onKeyDown={onKey} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        <div className="story-ctl">
          {!still && LAST > 0 && <button type="button" className="ghost" onClick={() => setPaused((p) => !p)}>{paused ? "Play" : "Pause"}</button>}
          <button type="button" className="ghost" ref={skip} onClick={onSkip}>Skip</button>
        </div>
        {still
          ? scenes.map((s, i) => <section key={i} className="scene on">{s}</section>)
          : <section key={scene} className="scene on" aria-live="polite">{scenes[scene]}</section>}
        {!still && LAST > 0 && (
          <div className="story-progress" role="group" aria-label="Scenes">
            {scenes.map((_, i) => (
              <button key={i} type="button" aria-label={`Scene ${i + 1} of ${scenes.length}`} aria-current={i === scene ? "step" : undefined}
                      onClick={() => go(i)}>
                <i style={{ width: i < scene ? "100%" : i === scene ? `${Math.min(100, (elapsed / sceneMs(i)) * 100)}%` : 0 }} />
              </button>
            ))}
          </div>
        )}
        {(still || scene === LAST) && (
          <div className="story-cta"><button type="button" className="primary" ref={see} onClick={onSee}>{brand ? `See the full ${brand} report →` : "Get started →"}</button></div>
        )}
      </div>
    </div>,
    document.body,
  );
}

// ------------------------------------------------------------------------------------- controller

/**
 * The guide, mounted once by the app. `story` is null when the showcase run cannot be read (a pass
 * holder does not see it), and then the welcome is shown alone. `auto` shows it on a first visit,
 * once per browser; `replay` increments when the top bar's "How it works" is pressed.
 */
export function Guide({ story, vars, auto, replay, onOpenShowcase }: {
  story: Story | null; vars: Vars; auto: boolean; replay: number;
  onOpenShowcase: () => void;
}) {
  const [open, setOpen] = useState(false);
  const back = useRef<HTMLElement | null>(null);
  const show = () => { back.current = document.activeElement as HTMLElement | null; setOpen(true); };

  useEffect(() => {
    if (!auto || open || !autoStarts(store)) return;
    const raf = requestAnimationFrame(show);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto]);
  // A replay is one press of the button: only its count starts it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (replay && !open) show(); }, [replay]);

  const end = (how: "done" | "skipped") => {
    markSeen(store, how);
    setOpen(false);
    // Focus goes back where it was, or to "How it works" when the guide started on its own.
    const to = back.current && back.current !== document.body ? back.current : document.querySelector<HTMLElement>("button.how");
    requestAnimationFrame(() => to?.focus());
  };

  if (!open) return null;
  return <StoryDialog story={story} vars={vars} onSkip={() => end("skipped")}
                      onSee={() => { end("done"); if (story) onOpenShowcase(); }} />;
}
