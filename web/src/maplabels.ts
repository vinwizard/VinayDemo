/**
 * Where each positioning-map label goes (PositioningMapView in components.tsx). No DOM here, so
 * `node --test` can check the rule the map must keep: every dot is named, and no two labels, or a
 * label and a dot, overlap. Widths come in measured, never guessed from the character count: a
 * guess ran "Kymriah" into "Where you want to be", and a dot with no room became a bare "1" that
 * only the legend could explain.
 */
export type Box = [number, number, number, number];
/** A dot and its label text; `w` is the text's measured width in map units. */
export type Dot = { x: number; y: number; r: number; text: string; w: number };
/** A label: one line per dot it names, its box, those dots, and its leader line when it sits apart. */
export type Label = { lines: string[]; box: Box; members: number[]; lead?: [number, number, number, number] };

export const LINE = 15;            // one label row: a 12-unit font plus room
export const MAX_CHARS = 30;       // a longer name is cut with "…"; the legend has it in full
const GAP = 4;                     // between a dot's edge and its label
const RINGS = 12;                  // label spots tried further out, each with a leader line
// right, left, above, below, the four diagonals: the eight spots beside a dot; then the angles
// between them, for the rings further out (degrees, y pointing down)
const ANGLES = [0, 180, 270, 90, 315, 225, 45, 135, 337.5, 202.5, 292.5, 247.5, 22.5, 157.5, 67.5, 112.5];

const hit = (a: Box, b: Box) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
const circle = (d: { x: number; y: number; r: number }): Box => [d.x - d.r, d.y - d.r, d.x + d.r, d.y + d.r];
export const short = (t: string) => (t.length > MAX_CHARS ? `${t.slice(0, MAX_CHARS - 1)}…` : t);

/** Dots touching each other get one label naming them all, a line each ("REDCap", "Medidata Rave"):
 * a tight cluster has no room left for a label per dot. */
function groups(dots: Dot[]): number[][] {
  const out: number[][] = [];
  dots.forEach((d, i) => {
    const g = out.find((m) => m.every((j) => Math.hypot(dots[j].x - d.x, dots[j].y - d.y) < dots[j].r + d.r + GAP));
    if (g) g.push(i);
    else out.push([i]);
  });
  return out;
}

/** Whether any stretch of a line runs inside a box (Liang–Barsky clipping); touching an edge does not count. */
export const crosses = ([x1, y1, x2, y2]: number[], b: Box) => {
  let t0 = 0, t1 = 1;
  const dx = x2 - x1, dy = y2 - y1;
  for (const [p, q] of [[-dx, x1 - b[0]], [dx, b[2] - x1], [-dy, y1 - b[1]], [dy, b[3] - y1]]) {
    if (p === 0) {
      if (q <= 0) return false;
    } else if (p < 0) {
      t0 = Math.max(t0, q / p);
    } else {
      t1 = Math.min(t1, q / p);
    }
  }
  return t0 < t1;
};

/**
 * -> the labels and the map's total height. Each label tries eight spots beside its dots, then
 * rings further out with a leader line, all inside the W x H plot; a label with no room at all
 * goes in a row under the plot, joined to its dot by a leader line. It is never left off.
 * `lines` (the drift arrow) are kept clear like dots, and no leader line runs through a label.
 */
export function placeLabels(dots: Dot[], W: number, H: number, lines: number[][] = []) {
  const boxes: Box[] = dots.map(circle);     // dots first, so index i is dot i
  const segs: number[][] = [...lines];       // the drift arrow and every leader drawn so far
  const labels: Label[] = [];
  let rows = 0;
  // the most crowded first: a dot in the middle of a cluster has the fewest ways out, and would be
  // boxed in if its neighbours took the space around it first
  const crowd = (g: number[]) => dots.filter((o) => g.some((i) => Math.hypot(o.x - dots[i].x, o.y - dots[i].y) < 40)).length;
  const order = groups(dots).map((g) => [crowd(g), g] as const).sort((a, b) => b[0] - a[0]).map(([, g]) => g);
  for (const members of order) {
    const ds = members.map((i) => dots[i]);
    const w = Math.max(...ds.map((d) => d.w)), h = LINE * ds.length;
    const cx = ds.reduce((s, d) => s + d.x, 0) / ds.length, cy = ds.reduce((s, d) => s + d.y, 0) / ds.length;
    const r = Math.max(...ds.map((d) => Math.hypot(d.x - cx, d.y - cy) + d.r));
    const empty = (b: Box) => !boxes.some((o) => hit(b, o)) && !segs.some((l) => crosses(l, b));
    const inPlot = (b: Box) => b[0] >= 2 && b[2] <= W - 2 && b[1] >= 2 && b[3] <= H - 2;
    // a leader line may pass over a dot (dots in a tight cluster leave it no other way out), never
    // through a label's text: boxes past the dots are labels
    const clear = (l: number[]) => boxes.every((o, i) => i < dots.length || !crosses(l, o));
    let box: Box | undefined, lead: Label["lead"];
    for (let ring = 0; ring <= RINGS && !box; ring++) {
      const g = r + GAP + ring * LINE;
      for (const a of ring ? ANGLES : ANGLES.slice(0, 8)) {
        // the box's side facing the dot sits at distance g from it, in direction a
        const cos = Math.cos((a * Math.PI) / 180), sin = Math.sin((a * Math.PI) / 180);
        const px = cx + g * cos, py = cy + g * sin;
        const x = cos > 0.3 ? px : cos < -0.3 ? px - w : px - w / 2;
        const y = sin > 0.3 ? py : sin < -0.3 ? py - h : py - h / 2;
        const b: Box = [x, y, x + w, y + h];
        const l = ring ? leader(cx, cy, r, b) : undefined;
        if (inPlot(b) && empty(b) && (!l || clear(l))) { box = b; lead = l; break; }
      }
    }
    if (!box) {  // no room in the plot: a row of its own under it, where its leader runs clear
      const y = H + 4 + rows * LINE, at = (x: number): Box => [x, y, x + w, y + h];
      rows += ds.length;
      const xs = [Math.min(Math.max(cx - w / 2, 2), W - w - 2)];
      for (let x = 2; x <= W - w - 2; x += 10) xs.push(x);
      // ponytail: a map crowded enough for no clear row path keeps its leader crossing; real maps
      // have at most eight dots (positioning.MAX_RIVALS + 2) and never get here
      const x = xs.find((x) => clear(leader(cx, cy, r, at(x)))) ?? xs[0];
      box = at(x);
      lead = leader(cx, cy, r, box);
    }
    boxes.push(box);
    if (lead) segs.push(lead);
    labels.push({ lines: ds.map((d) => d.text), box, members, lead });
  }
  return { labels, height: H + (rows ? rows * LINE + 8 : 0) };
}

/** From the dots' edge to the nearest point of the label's box. */
function leader(cx: number, cy: number, r: number, b: Box): [number, number, number, number] {
  const px = Math.min(Math.max(cx, b[0]), b[2]), py = Math.min(Math.max(cy, b[1]), b[3]);
  const len = Math.hypot(px - cx, py - cy) || 1;
  return [cx + ((px - cx) / len) * r, cy + ((py - cy) / len) * r, px, py];
}
