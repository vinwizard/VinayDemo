// The positioning map's layout rule, run by `node --test` (CI: web unit tests). No DOM: widths are
// a fixed 7 map units a character, wider than the map's real 12px font, so real text fits too.
import assert from "node:assert/strict";
import { test } from "node:test";
import { type Box, type Dot, layoutMap } from "./maplabels.ts";

const W = 360, H = 300;
const measure = (t: string) => t.length * 7;
const dot = (x: number, y: number, text: string, r = 7): Dot => ({ x, y, r, text });
const hit = (a: Box, b: Box) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
const UP = "↑ Up: talks more about “Leads in reliable biologic medicine manufacturing”";
const ACROSS = "→ Across: talks more about “Uses AI and advanced technology in research and development”";

function check(input: Dot[], leaders = true) {
  const m = layoutMap(input, W, H, UP, ACROSS, measure, [0, 1]);
  // (1) both axes named, in the chart, outside the plot, never over a label
  const plotTop = m.top, plotBottom = m.top + H;
  assert.ok(m.up.lines.join(" ") === UP && m.across.lines.join(" ") === ACROSS, "both axes carry their full name");
  assert.ok(m.up.lines.every((l) => measure(l) <= W - 8) && m.across.lines.every((l) => measure(l) <= W - 8), "names fit the chart");
  assert.ok(m.up.y + (m.up.lines.length - 1) * 15 < plotTop, "the up axis name sits above the plot");
  const lowest = Math.max(plotBottom, ...m.labels.map((l) => m.top + l.box[3]));
  assert.ok(m.across.y - 12 > lowest && m.across.y + (m.across.lines.length - 1) * 15 <= m.height, "the across name sits under the plot, in the chart");
  // (2) every dot its own label, its full name, nothing overlapping
  assert.deepEqual(m.labels.map((l) => l.dot).sort((a, b) => a - b), input.map((_, i) => i), "one label per dot");
  for (const [i, l] of m.labels.entries()) {
    const name = l.lines.join(" ");
    assert.equal(name, input[l.dot].text, "the dot's full name, never cut short");
    assert.ok(!name.includes("…") && !/^\d+$/.test(name), `a name, not a number or a stub: ${name}`);
    assert.ok(l.box[0] >= 0 && l.box[2] <= W && l.box[1] >= 0 && m.top + l.box[3] <= m.height, `${name} stays in the chart`);
    for (const o of m.labels.slice(i + 1)) assert.ok(!hit(l.box, o.box), `${name} overlaps ${o.lines.join(" ")}`);
    for (const d of m.dots) assert.ok(!hit(l.box, [d.x - d.r, d.y - d.r, d.x + d.r, d.y + d.r]), `${name} covers the dot ${d.text}`);
    if (leaders && l.lead) {  // a leader line never runs through another label's text
      const [x1, y1, x2, y2] = l.lead;
      for (const o of m.labels) {
        if (o === l) continue;
        for (let t = 0; t <= 1; t += 0.02) {
          const x = x1 + (x2 - x1) * t, y = y1 + (y2 - y1) * t;
          assert.ok(!(x > o.box[0] && x < o.box[2] && y > o.box[1] && y < o.box[3]), `${name}'s leader crosses ${o.lines}`);
        }
      }
    }
  }
  for (const [i, a] of m.dots.entries()) {  // dots that sat on one spot are drawn apart
    for (const b of m.dots.slice(i + 1)) assert.ok(Math.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r, `${a.text} hides ${b.text}`);
  }
  return m;
}

test("the gpt-6-luna Amgen map (run 0c55be2792): five rivals on one spot each get their own label", () => {
  // Drawn on 23 Sep: the Up axis had no name in the chart, four overlapping dots sat beside a list
  // of five stacked names, and one name was cut to "Johnson & Johnson Innovative …".
  const m = check([dot(229, 102, "Amgen", 9), dot(305, 88, "Where you want to be", 9),
    dot(216, 185, "AstraZeneca"), dot(222, 189, "Pfizer"), dot(229, 193, "Novartis"),
    dot(214, 201, "Johnson & Johnson"), dot(219, 199, "Merck & Co."), dot(207, 211, "Johnson & Johnson Innovative Medicine")]);
  assert.ok(m.moved, "the overlapping dots were moved apart to be told apart");
});

test("the gpt-6-luna Amgen map (run 61ab380205): pembrolizumab is named, not a bare number", () => {
  check([dot(189.5, 86.1, "Amgen", 9), dot(207.5, 36, "Where you want to be", 9),
    dot(114.3, 169.5, "pembrolizumab"), dot(121.8, 156, "trastuzumab"), dot(102, 173.8, "adalimumab"),
    dot(87.9, 192.2, "infliximab"), dot(312.5, 193.5, "Medidata Rave"), dot(304.4, 193, "REDCap")]);
});

test("the friend's Amgen map as drawn on 22 Sep: every dot named, nothing overlapping", () => {
  check([dot(289, 129, "Amgen", 9), dot(324, 94, "Where you want to be", 9), dot(115, 75, "Yescarta"),
    dot(118, 94, "Kymriah"), dot(135, 112, "Vertex Pharmaceuticals"), dot(130, 140, "Novartis"),
    dot(146, 166, "Johnson & Johnson"), dot(183, 240, "AbbVie")]);
});

test("dots on exactly the same spot are drawn apart and each named", () => {
  check([dot(60, 60, "Amgen", 9), dot(300, 250, "Where you want to be", 9),
    dot(180, 150, "REDCap"), dot(180, 150, "Medidata Rave"), dot(180, 150, "OpenClinica")]);
});

test("with no room left in the plot, a label goes in a row under it rather than off the chart", () => {
  const dots = [dot(20, 20, "Amgen", 9), dot(40, 40, "Where you want to be", 9),
    ...Array.from({ length: 38 }, (_, i) => dot(10 + (i % 8) * 45, 12 + Math.floor(i / 8) * 60, `Company ${i + 1}`))];
  const m = check(dots, false);  // forty dots can box a leader in; a real map has at most eight
  assert.ok(m.labels.some((l) => l.box[1] >= H && l.lead), "the chart grows a row for it, joined by a leader line");
});
