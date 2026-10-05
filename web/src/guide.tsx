// The first-visit guide on screen: the "how it works" story, then a spotlight tour of the screen:
// the report (Results, then Evidence), onboarding, or the nudge to Investigate after a live result.
// Copy, memory and what the story shows live in tour.ts; definitions come from glossary.ts through
// the same Term popover the report uses.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import type { TermKey } from "./glossary";
import { GLOSSARY } from "./glossary";
import type { Vars } from "./guideBus";
import { reportVars } from "./guideBus";
import { PHONE, Term } from "./popover";
import type { Part, Step, Story } from "./tour";
import { autoStarts, fill, INVESTIGATE_STEPS, markSeen, ONBOARD_STEPS, readySteps, replayPart, REPORT_STEPS, sceneMs, STORY_HEADLINES, STORY_WELCOME, termParts, welcomeFirst } from "./tour";

const store = (() => { try { return window.localStorage; } catch { return null; } })();
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
type Tour = "report" | "onboard" | "investigate";
const STEPS: Record<Tour, Step[]> = { report: REPORT_STEPS, onboard: ONBOARD_STEPS, investigate: INVESTIGATE_STEPS };

function Caption({ text, vars }: { text: string; vars: Vars }) {
  return <>{termParts(fill(text, vars)).map((p, i) =>
    "term" in p && p.term in GLOSSARY ? <Term key={i} k={p.term as TermKey}>{p.text}</Term> : <span key={i}>{p.text}</span>)}</>;
}

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
  // Without a story (the showcase run could not be read) the welcome is the only scene; its button
  // hands over to the tour.
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
          <div className="story-cta"><button type="button" className="primary" ref={see} onClick={onSee}>{brand ? `See the full ${brand} report →` : "Show me around →"}</button></div>
        )}
      </div>
    </div>,
    document.body,
  );
}

// -------------------------------------------------------------------------------------- spotlight

const PAD = 6;
const anchorsOf = (s: Step) => [...document.querySelectorAll<HTMLElement>(`[data-tour="${s.anchor}"]`)]
  .filter((el) => el.getClientRects().length);

/** The pinned Evidence tab strip, when the element sits below it: scrolling must clear it. */
const pinnedAbove = (el: HTMLElement) => {
  const top = document.querySelector<HTMLElement>(".ev-tabs");
  return top && top.getClientRects().length && !top.contains(el) ? top.offsetHeight : 0;
};

function Spotlight({ steps, vars, onEnd }: { steps: Step[]; vars: Vars; onEnd: (how: "done" | "skipped", focus?: HTMLElement) => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [capPos, setCapPos] = useState<CSSProperties>({});
  const cap = useRef<HTMLDivElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const step = steps[i];
  const last = i === steps.length - 1;

  const measure = useCallback(() => {
    const els = anchorsOf(step);
    if (!els.length) { setRect(null); return; }
    const rs = els.map((el) => el.getBoundingClientRect());
    const l = Math.min(...rs.map((r) => r.left)), t = Math.min(...rs.map((r) => r.top));
    setRect(new DOMRect(l - PAD, t - PAD, Math.max(...rs.map((r) => r.right)) - l + 2 * PAD,
                        Math.max(...rs.map((r) => r.bottom)) - t + 2 * PAD));
  }, [step]);

  useLayoutEffect(() => {
    // A step after one that opened a page or tab waits (up to 3 s) for what it lights up to render;
    // one whose element never appears (a part this run lacks) is passed over.
    const t0 = performance.now();
    let raf = 0;
    const find = () => {
      const el = anchorsOf(step)[0];
      if (!el) {
        if (performance.now() - t0 < 3000) { raf = requestAnimationFrame(find); return; }
        if (last) onEnd("done"); else setI(i + 1);
        return;
      }
      // A tab can sit off-screen in the phone's sideways tab strip: bring it in first.
      el.scrollIntoView({ block: "nearest", inline: "center" });
      const r = el.getBoundingClientRect(), clear = pinnedAbove(el);
      if (r.top < clear || r.bottom > window.innerHeight * (window.matchMedia(PHONE).matches ? 0.55 : 0.85)) {
        window.scrollTo({ top: window.scrollY + r.top - clear - 16, behavior: reduced() ? "auto" : "smooth" });
      }
      measure();
    };
    setRect(null);
    find();
    next.current?.focus();
    const again = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(measure); };
    window.addEventListener("scroll", again, true);
    window.addEventListener("resize", again);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("scroll", again, true); window.removeEventListener("resize", again); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, measure]);

  // The caption sits below its target when it fits, else above, kept inside the window. On a phone
  // CSS makes it a bottom sheet, as the glossary popover is.
  useLayoutEffect(() => {
    const c = cap.current;
    if (!c || !rect || window.matchMedia(PHONE).matches) { setCapPos({}); return; }
    const w = c.offsetWidth, h = c.offsetHeight;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - w - 8));
    const below = rect.bottom + 12;
    setCapPos(below + h < window.innerHeight - 8 ? { left, top: below } : { left, top: Math.max(8, rect.top - h - 12) });
  }, [rect]);

  const forward = () => {
    // A step with an action opens what it points at (a page or a tab); the next step lights up
    // something there, and on the last step focus lands on it, not back on the button.
    const target = step.action ? anchorsOf(step)[0] : undefined;
    target?.click();
    if (!last) { setI(i + 1); return; }
    onEnd("done", target);
  };
  // Back cannot cross a page or tab the tour has opened: what it lit up there is gone.
  const canBack = i > 0 && !steps[i - 1].action;
  const onKey = (e: ReactKeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape" && !document.querySelector(".popover")) { e.preventDefault(); onEnd("skipped"); }
    else if (e.key === "ArrowRight") { e.preventDefault(); forward(); }
    else if (e.key === "ArrowLeft" && canBack) { e.preventDefault(); setI(i - 1); }
    else trapTab(e);
  };

  return createPortal(
    <>
      <div className="tour-block" aria-hidden />
      <div className={`tour-spot${rect ? "" : " none"}`} aria-hidden
           style={rect ? { left: rect.left, top: rect.top, width: rect.width, height: rect.height } : undefined} />
      <div ref={cap} className="tour-cap" role="dialog" aria-modal="true" aria-labelledby="tour-title"
           aria-describedby="tour-text" style={capPos} onKeyDown={onKey}>
        <div key={i} className="tour-step">
          <span className="tour-count">Step {i + 1} of {steps.length}</span>
          <h4 id="tour-title">{step.title}</h4>
          <p id="tour-text" aria-live="polite"><Caption text={step.text} vars={vars} /></p>
        </div>
        <div className="tour-row">
          <button type="button" className="linky tour-skip" onClick={() => onEnd("skipped")}>Skip tour</button>
          <span className="tour-dots" aria-hidden>
            {steps.map((_, k) => <i key={k} className={k === i ? "on" : k < i ? "past" : ""} />)}
          </span>
          <span className="tour-nav">
            <button type="button" className="ghost" disabled={!canBack} onClick={() => setI(i - 1)}>Back</button>
            <button type="button" className="primary" ref={next} onClick={forward}>{step.action ?? (last ? "Done" : "Next")}</button>
          </span>
        </div>
      </div>
    </>,
    document.body,
  );
}

// ------------------------------------------------------------------------------------- controller

type Active = { kind: "story"; then?: "report" | "onboard" } | { kind: "tour"; part: Tour; steps: Step[] } | null;

/**
 * Waits (a few frames, up to 3 s) for a screen's first anchor, since reports load after the click.
 * The tour starts at the first step on screen (a replay on the Evidence page starts there), keeps
 * the steps on this screen that are there, and every step past the first one that opens another
 * page or tab: those render only when the tour gets to them.
 */
function whenAnchored(steps: Step[], then: (present: Step[]) => void) {
  const t0 = performance.now();
  const look = () => {
    const k = steps.findIndex((s) => anchorsOf(s).length);
    if (k < 0) {
      if (performance.now() - t0 > 3000) then([]); else requestAnimationFrame(look);
      return;
    }
    const rest = steps.slice(k);
    const opens = rest.findIndex((s) => s.action);
    const here = opens < 0 ? rest : rest.slice(0, opens + 1);
    then([...here.filter((s) => anchorsOf(s).length), ...rest.slice(here.length)]);
  };
  requestAnimationFrame(look);
}

/**
 * The guide, mounted once by the app. `story` is null when the showcase run cannot be read, and
 * then the welcome is shown alone before the tour. `auto` asks for the story on a first visit, once
 * per browser; `replay` increments when the top bar's "How it works" is pressed, after the app has
 * switched to the tab that tour needs. Tours are asked for through guideBus.requestTour.
 */
export function Guide({ story, vars, auto, replay, onOpenShowcase }: {
  story: Story | null; vars: Vars; auto: boolean; replay: number;
  onOpenShowcase: () => void;
}) {
  const [active, setActive] = useState<Active>(null);
  const busy = useRef(false);
  const back = useRef<HTMLElement | null>(null);
  const storyRef = useRef(story);
  storyRef.current = story;

  const startTour = useCallback((part: Tour, auto: boolean, welcomed = false) => {
    if (busy.current || (auto && !autoStarts(store, part))) return;
    // The story goes first: a tour asked for before it has played waits for the next screen.
    if (auto && part === "onboard" && storyRef.current && autoStarts(store, "story")) return;
    busy.current = true;
    if (!welcomed && part !== "investigate" && welcomeFirst(store, !!storyRef.current, auto)) {
      setActive({ kind: "story", then: part }); return;
    }
    whenAnchored(STEPS[part], (present) => {
      // Read the report's numbers only now: after the story, the report loads while this waits.
      const steps = readySteps(present, part === "onboard" ? {} : reportVars());
      if (steps.length) setActive({ kind: "tour", part, steps });
      else busy.current = false;
    });
  }, []);
  const end = useCallback((part: Part, how: "done" | "skipped", focus?: HTMLElement, then?: "report" | "onboard") => {
    markSeen(store, part, how, then);
    busy.current = false;
    setActive(null);
    // Focus goes back where it was, or to "How it works" when the guide started on its own.
    const to = focus ?? (back.current && back.current !== document.body && back.current.isConnected ? back.current : null)
      ?? document.querySelector<HTMLElement>("button.how");
    requestAnimationFrame(() => to?.focus());
  }, []);

  useEffect(() => {
    const on = (e: Event) => { const { part, auto } = (e as CustomEvent).detail; startTour(part, auto); };
    window.addEventListener("offmessage:tour", on);
    return () => window.removeEventListener("offmessage:tour", on);
  }, [startTour]);

  useEffect(() => {
    if (!auto || !story || busy.current || !autoStarts(store, "story")) return;
    busy.current = true;
    back.current = document.activeElement as HTMLElement | null;
    let shown = false;
    const raf = requestAnimationFrame(() => { shown = true; setActive({ kind: "story" }); });
    // Only a story that never appeared gives the guide back; one on screen ends through `end`.
    return () => { cancelAnimationFrame(raf); if (!shown) busy.current = false; };
  }, [auto, story]);

  useEffect(() => {
    if (!replay || busy.current) return;
    back.current = document.activeElement as HTMLElement | null;
    const part = replayPart(!!story, !!document.querySelector('[data-tour="headline"], [data-tour="ev-tabs"]'));
    if (part === "story") { busy.current = true; requestAnimationFrame(() => setActive({ kind: "story" })); return; }
    startTour(part, false);
    // A replay is one press of the button: only its count starts it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replay]);

  if (active?.kind === "story" && (story || active.then)) {
    const then = active.then;
    return <StoryDialog story={then ? null : story} vars={vars} onSkip={() => end("story", "skipped", undefined, then)}
                        onSee={() => {
                          end("story", "done");
                          if (then) { startTour(then, false, true); return; }
                          onOpenShowcase(); startTour("report", false);
                        }} />;
  }
  if (active?.kind === "tour") {
    const part = active.part;
    return <Spotlight steps={active.steps} vars={part === "onboard" ? {} : reportVars()} onEnd={(how, focus) => end(part, how, focus)} />;
  }
  return null;
}
