import type { MapPoint, Run } from "../api";
import { plural } from "../labels";
import { LINE, layoutMap } from "../maplabels";
import { PHONE, Popover, Term } from "../popover";
import { listed } from "./util";
import { Block, SAMPLE_NOTE } from "./ui";

const MAP_W = 360, MAP_H = 300, MAP_PAD = 36, MAP_FONT = 12;

let measurer: CanvasRenderingContext2D | null | undefined;
/** A label's real width in map units (the SVG is MAP_W units wide at a 12-unit font), in the page's
 * own font. Only without a canvas does it fall back to a generous estimate. */
const measure = (text: string, bold = false) => {
  measurer ??= document.createElement("canvas").getContext("2d");
  if (!measurer) return text.length * MAP_FONT * 0.65;
  measurer.font = `${bold ? 650 : 400} ${MAP_FONT}px ${getComputedStyle(document.body).fontFamily}`;
  return measurer.measureText(text).width;
};

/** An axis in words, above or below the map, never inside it: a claim the axis measures (a live
 * map), or its two ends (the authored sample). */
const axisName = (ends: string[], across: boolean) => {
  const dir = across ? "→ Across:" : "↑ Up:";
  return ends.length === 1 ? `${dir} talks more about “${ends[0]}”`
    : ends.length === 2 ? `${dir} from “${ends[0]}” to “${ends[1]}”`
    : `${dir} drawn before axes were named after your claims; measure again to name it`;
};

/** What one dot was built from, verbatim, and how close it sits to the brand as AI describes it. */
function PointDetail({ p, title, site, brand, sample }: {
  p: MapPoint; title: string; site: boolean; brand: string; sample: boolean;
}) {
  const n = p.sentences.length;
  return (
    <>
      <strong className="pop-title">{title}</strong>
      <p className="muted">
        {sample && <><span className="tag sample">sample</span> Placed by hand, not computed. </>}
        {p.kind === "seen" ? `Built from ${plural(n, "sentence")} in AI's answers about ${brand}.`
          : p.kind === "intended" ? (site ? `Built from ${plural(n, "positioning line")} on your site.`
            : `Built from the ${plural(n, "claim")} you weighted; a heavier weight pulls harder.`)
          : `Built from ${plural(n, "sentence")} in buyer answers that name ${p.name}.`}
      </p>
      {p.similarity != null && (
        <p>Similarity to how AI describes {brand}: <strong>{p.similarity.toFixed(2)}</strong> (1 is the same
          meaning, 0 unrelated).</p>
      )}
      {p.sentences.map((s) => <p key={s} className="quote">{s}</p>)}
    </>
  );
}

/**
 * The positioning map (positioning.py): the brand as AI describes it, as its site describes it and
 * each rival, flattened to two axes by meaning. One arrow is the drift. Every dot, and its name in
 * the legend, opens the sentences it was built from. A picture of similarity, never a score.
 */
export function PositioningMapView({ run }: { run: Run }) {
  const m = run.positioning;
  if (!m) return null;
  const brand = run.profile.name, sample = m.provenance !== "live_api", site = m.aim !== "intended";
  const aim = site ? "where your site aims" : "where you want to be";
  const found = m.reason ? "not drawn"
    : `AI places ${brand} closest to ${listed(m.closest)}`
      + (m.toward ? `; ${site ? "your site aims" : "you want to be"} further toward “${m.toward}”`
        : `; ${aim} is somewhere else on the map`);
  const body = () => {
    if (m.reason) return <p className="muted" style={{ margin: 0 }}>{m.reason}</p>;
    const order = { seen: 0, intended: 1, rival: 2 };
    const pts = [...m.points].sort((a, b) => order[a.kind] - order[b.kind] || (b.similarity ?? 0) - (a.similarity ?? 0));
    const mx = Math.max(...pts.map((p) => Math.abs(p.x)), 1e-9), my = Math.max(...pts.map((p) => Math.abs(p.y)), 1e-9);
    const scale = Math.min((MAP_W / 2 - MAP_PAD) / mx, (MAP_H / 2 - MAP_PAD) / my);
    // bold widths for every text: the brand's labels and the axis names are bold, and wider is safe
    const at = layoutMap(pts.map((p) => ({ x: MAP_W / 2 + p.x * scale, y: MAP_H / 2 - p.y * scale,
                                           r: p.kind === "rival" ? 7 : 9, text: p.kind === "intended" ? aim : p.name })),
                         MAP_W, MAP_H, axisName(m.y_axis, false), axisName(m.x_axis, true), (t) => measure(t, true), [0, 1]);
    const dots = at.dots.map((d, i) => ({ ...d, p: pts[i] }));
    const { labels, height, top } = at;
    const [seenDot, aimDot] = dots;
    const dx = aimDot.x - seenDot.x, dy = aimDot.y - seenDot.y, len = Math.hypot(dx, dy);
    const ux = dx / len, uy = dy / len, tip = [aimDot.x - ux * (aimDot.r + 2), aimDot.y - uy * (aimDot.r + 2)];
    const title = (d: (typeof dots)[number]) => d.p.kind === "seen" ? `${brand}, as AI describes it`
      : d.p.kind === "intended" ? `${brand}, ${aim}` : `${d.p.name}, as AI describes it`;
    return (
      <>
        <p className="muted" style={{ margin: 0 }}>
          {sample && <>{SAMPLE_NOTE} The dots were placed by hand. </>}
          A <Term k="positioning_map"
                  note={m.explained != null && `These two axes show ${Math.round(m.explained * 100)}% of the differences between the dots; the rest is flattened away.`}>
            similarity picture</Term>, not a measurement: dots close together were described in similar words.
          The arrow runs from where AI places {brand} to {aim}. Tap a dot for the sentences behind it.
        </p>
        <div className="pmap" style={{ aspectRatio: `${MAP_W} / ${height}` }}>
          <svg viewBox={`0 0 ${MAP_W} ${height}`} aria-hidden="true">
            {at.up.lines.map((t, j) => (
              <text key={t} className="pmap-title" x={MAP_W / 2} y={at.up.y + j * LINE} textAnchor="middle">{t}</text>
            ))}
            {at.across.lines.map((t, j) => (
              <text key={t} className="pmap-title" x={MAP_W / 2} y={at.across.y + j * LINE} textAnchor="middle">{t}</text>
            ))}
            <g transform={`translate(0 ${top})`}>
            <rect className="pmap-frame" x={0} y={0} width={MAP_W} height={MAP_H} />
            <line className="pmap-axis" x1={MAP_W / 2} y1={0} x2={MAP_W / 2} y2={MAP_H} />
            <line className="pmap-axis" x1={0} y1={MAP_H / 2} x2={MAP_W} y2={MAP_H / 2} />
            {len > seenDot.r + aimDot.r + 4 && (
              <>
                <line className="pmap-drift" x1={seenDot.x + ux * (seenDot.r + 2)} y1={seenDot.y + uy * (seenDot.r + 2)}
                      x2={tip[0] - ux * 8} y2={tip[1] - uy * 8} />
                <polygon className="pmap-head" points={`${tip[0]},${tip[1]} ${tip[0] - ux * 10 - uy * 5},${tip[1] - uy * 10 + ux * 5} ${tip[0] - ux * 10 + uy * 5},${tip[1] - uy * 10 - ux * 5}`} />
              </>
            )}
            {dots.map((d) => <circle key={`${d.p.kind}-${d.p.name}`} className={`pmap-dot ${d.p.kind}`} cx={d.x} cy={d.y} r={d.r} />)}
            {labels.map((l) => (
              <g key={l.dot}>
                {l.lead && <line className="pmap-lead" x1={l.lead[0]} y1={l.lead[1]} x2={l.lead[2]} y2={l.lead[3]} />}
                {l.lines.map((t, j) => (
                  <text key={t} className={`pmap-label ${dots[l.dot].p.kind}`} x={l.box[0]}
                        y={l.box[1] + LINE * (j + 1) - 3.5}>{t}</text>
                ))}
              </g>
            ))}
            </g>
          </svg>
          {dots.map((d) => (
            <span key={`${d.p.kind}-${d.p.name}`} className="pmap-hit"
                  style={{ left: `${(100 * d.x) / MAP_W}%`, top: `${(100 * (top + d.y)) / height}%` }}>
              <Popover wide label={title(d)} className="pmap-tap"
                       trigger={<span className="sr-only">{title(d)}</span>}>
                <PointDetail p={d.p} title={title(d)} site={site} brand={brand} sample={sample} />
              </Popover>
            </span>
          ))}
        </div>
        {at.moved && (
          <p className="muted" style={{ margin: 0 }}>
            Dots that sat on top of each other are drawn a little apart, so each can carry its name.
          </p>
        )}
        <ul className="pmap-legend">
          {dots.map((d) => (
            <li key={`${d.p.kind}-${d.p.name}`}>
              <Popover wide label={title(d)} className="chip"
                       trigger={<>
                         <span className={`pmap-swatch ${d.p.kind}`} aria-hidden="true" />
                         {d.p.kind === "seen" ? `${brand}, as AI sees it` : d.p.kind === "intended" ? aim[0].toUpperCase() + aim.slice(1) : d.p.name}
                       </>}>
                <PointDetail p={d.p} title={title(d)} site={site} brand={brand} sample={sample} />
              </Popover>
            </li>
          ))}
        </ul>
        {m.notes.map((n) => <p key={n} className="muted" style={{ margin: 0 }}>{n}</p>)}
      </>
    );
  };
  return (
    <Block open={!window.matchMedia(PHONE).matches} title="Positioning map" found={found}>
      {body()}
    </Block>
  );
}
