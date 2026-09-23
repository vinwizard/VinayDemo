/**
 * The positioning map's layout (PositioningMapView in components.tsx). No DOM here, so
 * `node --test` can check the rule the map must keep: both axes are named, in the chart and outside
 * the plot, and every dot carries its own full name, with no two labels (or a label and a dot)
 * overlapping. Widths come in measured, never guessed: a guess ran "Kymriah" into "Where you want
 * to be", a dot with no room became a bare "1", and dots drawn on top of each other could not be
 * told apart.
 */
export type Box = [number, number, number, number];
/** A dot and its label text, in plot units. */
export type Dot = { x: number; y: number; r: number; text: string };
/** A dot's label: its lines (one, unless the name is wider than the plot), box, and leader line. */
export type Label = { dot: number; lines: string[]; box: Box; lead?: [number, number, number, number] };
/** An axis name: its lines and the baseline of the first, in whole-chart units. */
export type Title = { lines: string[]; y: number };

export const LINE = 15;            // one text row: a 12-unit font plus room
const GAP = 4;                     // between a dot's edge and its label
const RINGS = 12;                  // label spots tried further out, each with a leader line
// right, left, above, below, the four diagonals: the eight spots beside a dot; then the angles
// between them, for the rings further out (degrees, y pointing down)
const ANGLES = [0, 180, 270, 90, 315, 225, 45, 135, 337.5, 202.5, 292.5, 247.5, 22.5, 157.5, 67.5, 112.5];

const hit = (a: Box, b: Box) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
const circle = (d: Dot): Box => [d.x - d.r, d.y - d.r, d.x + d.r, d.y + d.r];

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

/** Words into lines no wider than `max`; a single word wider than that keeps a line of its own. */
export function wrap(text: string, max: number, measure: (t: string) => number): string[] {
  const lines: string[] = [];
  for (const word of text.split(" ")) {
    const last = lines.length ? `${lines[lines.length - 1]} ${word}` : word;
    if (lines.length && measure(last) <= max) lines[lines.length - 1] = last;
    else lines.push(word);
  }
  return lines;
}

/**
 * Dots on top of each other are pushed apart until each can be seen, and so named: a similarity
 * picture, so a few units matter less than telling the dots apart. `moved` says whether any moved.
 */
function spread(dots: Dot[], W: number, H: number): { dots: Dot[]; moved: boolean } {
  const ds = dots.map((d) => ({ ...d }));
  let moved = false;
  for (let round = 0; round < 200; round++) {
    let clash = false;
    for (let i = 0; i < ds.length; i++) {
      for (let j = i + 1; j < ds.length; j++) {
        const a = ds[i], b = ds[j], need = a.r + b.r + 3;
        let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
        if (d >= need) continue;
        clash = moved = true;
        if (d < 1e-6) { dx = Math.cos(j); dy = Math.sin(j); d = 1; }  // the same spot: a fixed direction
        const push = (need - d) / 2 + 0.01;
        a.x -= (dx / d) * push; a.y -= (dy / d) * push;
        b.x += (dx / d) * push; b.y += (dy / d) * push;
      }
    }
    for (const d of ds) {
      d.x = Math.min(Math.max(d.x, d.r + 2), W - d.r - 2);
      d.y = Math.min(Math.max(d.y, d.r + 2), H - d.r - 2);
    }
    if (!clash) break;
  }
  return { dots: ds, moved };
}

/** From a dot's edge to the nearest point of its label's box. */
function leader(d: Dot, b: Box): [number, number, number, number] {
  const px = Math.min(Math.max(d.x, b[0]), b[2]), py = Math.min(Math.max(d.y, b[1]), b[3]);
  const len = Math.hypot(px - d.x, py - d.y) || 1;
  return [d.x + ((px - d.x) / len) * d.r, d.y + ((py - d.y) / len) * d.r, px, py];
}

/**
 * -> the whole chart: the dots (spread apart where they sat on top of each other), a label per dot,
 * both axis names, where the W x H plot starts (`top`) and the chart's total height. Each label
 * tries eight spots beside its dot, then rings further out with a leader line; one with no room
 * goes in a row under the plot, joined to its dot by a leader line. A label is never left off,
 * cut short or replaced by a number. The drift arrow (`arrow`, dot indices) is kept clear, and no
 * leader line runs through a label. Labels and dots are in plot units; the titles' `y` is not.
 */
export function layoutMap(input: Dot[], W: number, H: number, up: string, across: string,
                          measure: (text: string) => number, arrow?: [number, number]) {
  const { dots, moved } = spread(input, W, H);
  const upTitle = wrap(up, W - 8, measure);
  const top = upTitle.length * LINE + 8;
  const boxes: Box[] = dots.map(circle);     // dots first, so index i is dot i
  const segs: number[][] = arrow ? [[dots[arrow[0]].x, dots[arrow[0]].y, dots[arrow[1]].x, dots[arrow[1]].y]] : [];
  const labels: Label[] = [];
  let rows = 0;
  // the most crowded first: a dot in the middle of a cluster has the fewest ways out
  const crowd = (i: number) => dots.filter((o) => Math.hypot(o.x - dots[i].x, o.y - dots[i].y) < 40).length;
  const order = dots.map((_, i) => i).sort((a, b) => crowd(b) - crowd(a) || a - b);
  for (const i of order) {
    const d = dots[i];
    const lines = wrap(d.text, W - 8, measure);
    const w = Math.max(...lines.map(measure)), h = LINE * lines.length;
    const empty = (b: Box) => !boxes.some((o) => hit(b, o)) && !segs.some((l) => crosses(l, b));
    const inPlot = (b: Box) => b[0] >= 2 && b[2] <= W - 2 && b[1] >= 2 && b[3] <= H - 2;
    // a leader line may pass over a dot (a tight cluster leaves it no other way out), never through
    // a label's text: boxes past the dots are labels
    const clear = (l: number[]) => boxes.every((o, j) => j < dots.length || !crosses(l, o));
    let box: Box | undefined, lead: Label["lead"];
    for (let ring = 0; ring <= RINGS && !box; ring++) {
      const g = d.r + GAP + ring * LINE;
      for (const a of ring ? ANGLES : ANGLES.slice(0, 8)) {
        // the box's side facing the dot sits at distance g from it, in direction a
        const cos = Math.cos((a * Math.PI) / 180), sin = Math.sin((a * Math.PI) / 180);
        const px = d.x + g * cos, py = d.y + g * sin;
        const x = cos > 0.3 ? px : cos < -0.3 ? px - w : px - w / 2;
        const y = sin > 0.3 ? py : sin < -0.3 ? py - h : py - h / 2;
        const b: Box = [x, y, x + w, y + h];
        const l = ring ? leader(d, b) : undefined;
        if (inPlot(b) && empty(b) && (!l || clear(l))) { box = b; lead = l; break; }
      }
    }
    if (!box) {  // no room in the plot: a row of its own under it, where its leader runs clear
      const y = H + 4 + rows * LINE, at = (x: number): Box => [x, y, x + w, y + h];
      rows += lines.length;
      const xs = [Math.min(Math.max(d.x - w / 2, 2), W - w - 2)];
      for (let x = 2; x <= W - w - 2; x += 10) xs.push(x);
      // ponytail: a map crowded enough for no clear row path keeps its leader crossing; real maps
      // have at most eight dots (positioning.MAX_RIVALS + 2) and never get here
      box = at(xs.find((x) => clear(leader(d, at(x)))) ?? xs[0]);
      lead = leader(d, box);
    }
    boxes.push(box);
    if (lead) segs.push(lead);
    labels.push({ dot: i, lines, box, lead });
  }
  const below = top + H + (rows ? rows * LINE + 8 : 0);
  const acrossTitle = wrap(across, W - 8, measure);
  const upName: Title = { lines: upTitle, y: LINE - 3.5 };
  const acrossName: Title = { lines: acrossTitle, y: below + LINE + 2 };
  return { dots, moved, labels, top, up: upName, across: acrossName, height: below + acrossTitle.length * LINE + 8 };
}
