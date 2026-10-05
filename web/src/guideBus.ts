// How the rest of the app talks to the first-visit guide (guide.tsx) without importing it.
import { useEffect } from "react";
import type { RefObject } from "react";

/** Everything a caption can fill in: the report's own numbers, so no caption states a figure of its own. */
export type Vars = Record<string, string | number | null | undefined>;

let shown: Vars = {};
/** The numbers of the report on screen, for the report tour's captions. */
export const reportVars = () => shown;

/** Asks the guide for a tour. `auto` tours start only once per browser; replays always do. */
export function requestTour(part: "report" | "onboard" | "investigate", auto: boolean) {
  window.dispatchEvent(new CustomEvent("offmessage:tour", { detail: { part, auto } }));
}

/**
 * A report registers its numbers for the captions and, the first time one is seen, asks for the
 * tour. A report on a tab out of view (the onboarding one behind History) leaves the numbers alone.
 */
export function useReportTour(vars: Vars, el: RefObject<HTMLElement | null>) {
  useEffect(() => { if (el.current?.getClientRects().length) shown = vars; });
  useEffect(() => { requestTour("report", true); }, []);
}
