// The positioning map's label rule, run by `node --test` (CI: web unit tests). No DOM: widths are
// a fixed 7 map units a character, wider than the map's real 12px font, so real text fits too.
import assert from "node:assert/strict";
import { test } from "node:test";
import { type Box, type Dot, placeLabels } from "./maplabels.ts";

const W = 360, H = 300;
const width = (t: string) => t.length * 7;
const dot = (x: number, y: number, text: string, r = 7): Dot => ({ x, y, r, text, w: width(text) });
const hit = (a: Box, b: Box) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

function check(dots: Dot[], leaders = true) {
  const { labels, height } = placeLabels(dots, W, H);
  const named = labels.flatMap((l) => l.members).sort((a, b) => a - b);
  assert.deepEqual(named, dots.map((_, i) => i), "every dot is named by exactly one label");
  for (const [i, l] of labels.entries()) {
    const text = l.lines.join(" · ");
    assert.deepEqual(l.lines, l.members.map((m) => dots[m].text), "a line per dot, its own name");
    assert.ok(l.lines.every((n) => !/^\d+$/.test(n)), `a label is a name, never a bare number: ${text}`);
    assert.ok(l.box[0] >= 0 && l.box[2] <= W && l.box[1] >= 0 && l.box[3] <= height, `${text} stays on the map`);
    for (const o of labels.slice(i + 1)) assert.ok(!hit(l.box, o.box), `${text} overlaps ${o.lines}`);
    for (const d of dots) {
      assert.ok(!hit(l.box, [d.x - d.r, d.y - d.r, d.x + d.r, d.y + d.r]), `${text} covers the dot ${d.text}`);
    }
    if (leaders && l.lead) {  // a leader line never runs through another label's text
      const [x1, y1, x2, y2] = l.lead;
      for (const o of labels) {
        if (o === l) continue;
        for (let t = 0; t <= 1; t += 0.02) {
          const x = x1 + (x2 - x1) * t, y = y1 + (y2 - y1) * t;
          assert.ok(!(x > o.box[0] && x < o.box[2] && y > o.box[1] && y < o.box[3]), `${text}'s leader crosses ${o.lines}`);
        }
      }
    }
  }
  return labels;
}

test("the Amgen map from the gpt-6-luna run: pembrolizumab is named, not a bare number", () => {
  // Exact dot positions from run 61ab380205 (22 Sep 2026). The old placement found no free spot
  // for pembrolizumab and drew it as "1"; REDCap and Medidata Rave sit on top of each other.
  const labels = check([dot(189.5, 86.1, "Amgen", 9), dot(207.5, 36, "Where you want to be", 9),
    dot(114.3, 169.5, "pembrolizumab"), dot(121.8, 156, "trastuzumab"), dot(102, 173.8, "adalimumab"),
    dot(87.9, 192.2, "infliximab"), dot(312.5, 193.5, "Medidata Rave"), dot(304.4, 193, "REDCap")]);
  assert.ok(labels.some((l) => l.lines.includes("pembrolizumab")), "named, in its own or a shared label");
  assert.ok(labels.some((l) => l.lines.join() === "Medidata Rave,REDCap"), "the two dots on one spot share a label");
});

test("the friend's Amgen map as drawn on 22 Sep: every dot named, nothing overlapping", () => {
  // Positions read off the screenshot: "Kymriah" ran into "Where you want to be", and Vertex
  // Pharmaceuticals had no room, so it was drawn as "1".
  check([dot(289, 129, "Amgen", 9), dot(324, 94, "Where you want to be", 9), dot(115, 75, "Yescarta"),
    dot(118, 94, "Kymriah"), dot(135, 112, "Vertex Pharmaceuticals"), dot(130, 140, "Novartis"),
    dot(146, 166, "Johnson & Johnson"), dot(183, 240, "AbbVie")]);
});

test("dots on the same spot share one label that names them all", () => {
  const labels = check([dot(200, 150, "Amgen", 9), dot(100, 250, "REDCap"), dot(103, 251, "Medidata Rave")]);
  assert.ok(labels.some((l) => l.lines.join() === "REDCap,Medidata Rave" && l.members.length === 2));
});

test("a crowded cluster still names every dot: touching dots share a label, a line each", () => {
  const names = ["pembrolizumab", "trastuzumab", "adalimumab", "infliximab", "nivolumab", "rituximab",
    "bevacizumab", "filgrastim"];
  const labels = check(names.map((n, i) => dot(60 + (i % 4) * 16, 150 + Math.floor(i / 4) * 16, n)));
  assert.ok(labels.length < names.length && labels.every((l) => l.lines.length <= 2));
});

test("with no room left in the plot, a label goes in a row under it rather than off the map", () => {
  const dots = Array.from({ length: 40 }, (_, i) => dot(10 + (i % 8) * 45, 12 + Math.floor(i / 8) * 60, `Company ${i + 1}`));
  const { labels, height } = placeLabels(dots, W, H);
  assert.ok(height > H && labels.some((l) => l.box[1] >= H), "the map grows a row for it");
  assert.ok(labels.filter((l) => l.box[1] >= H).every((l) => l.lead), "joined to its dot by a leader line");
  check(dots, false);  // forty dots can box a leader in; a real map has at most eight
});
