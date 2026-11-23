import { useState } from "react";
import { describeDaily, linePoints, niceMax, pathFrom, ticks } from "../lib/chartMath";
import { useInView } from "../hooks/motion";

/*
 * Hand-built SVG charts. One hue per chart (the title names the series), recessive
 * grid, hover tooltip on every mark, and a plain-text summary plus a table for
 * screen readers. Marks animate in once, when the chart first scrolls into view;
 * the reduced-motion media query in index.css renders them in final state.
 */

function useTip() {
  const [tip, setTip] = useState(null);
  const show = (e, text) => {
    const box = e.currentTarget.ownerSVGElement.getBoundingClientRect();
    const mark = e.currentTarget.getBoundingClientRect();
    setTip({ text, left: mark.left - box.left + mark.width / 2, top: mark.top - box.top });
  };
  return [tip, show, () => setTip(null)];
}

function Tip({ tip }) {
  if (!tip) return null;
  return (
    <span
      role="presentation"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-sm bg-ink px-1.5 py-0.5 font-mono text-[11px] text-paper"
      style={{ left: tip.left, top: tip.top - 6 }}
    >
      {tip.text}
    </span>
  );
}

function ChartFrame({ title, summary, children, table }) {
  const [ref, seen] = useInView({ once: true });
  return (
    <figure ref={ref} className={`rounded-lg border border-rule bg-surface p-4 ${seen ? "chart-in" : "chart-wait"}`}>
      <figcaption className="mb-3 text-sm font-medium text-ink">{title}</figcaption>
      <p className="sr-only">{summary}</p>
      <div className="relative" aria-hidden="true">{children}</div>
      <table className="sr-only">
        <caption>{title}</caption>
        <tbody>
          {table.map(([k, v]) => (
            <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

const W = 940;
const H = 170;
const PAD = { l: 32, r: 12, t: 10, b: 22 };

/** Questions per day: a 2px line that draws itself in, with point hover. */
export function DailyLine({ days }) {
  const [tip, show, hide] = useTip();
  const values = days.map((d) => d.questions);
  const top = niceMax(Math.max(...values, 0));
  const box = { x0: PAD.l, x1: W - PAD.r, y0: PAD.t, y1: H - PAD.b, max: top };
  const pts = linePoints(values, box);
  const line = pathFrom(pts);
  const area = pts.length ? `${line} L${pts.at(-1).x} ${box.y1} L${pts[0].x} ${box.y1} Z` : "";
  const slot = pts.length > 1 ? pts[1].x - pts[0].x : box.x1 - box.x0;
  const y = (v) => box.y1 - (v / top) * (box.y1 - box.y0);
  const label = (d) => d.date.slice(5);
  const xLabels = [0, Math.floor((days.length - 1) / 2), days.length - 1].filter((v, i, a) => a.indexOf(v) === i);

  return (
    <ChartFrame title="Questions per day" summary={describeDaily(days)} table={days.map((d) => [d.date, d.questions])}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full overflow-visible" onMouseLeave={hide}>
        {ticks(top).map((t) => (
          <g key={t}>
            <line x1={box.x0} x2={box.x1} y1={y(t)} y2={y(t)} className="stroke-rule-soft" strokeWidth="1" />
            <text x={box.x0 - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted font-mono text-[10px]">{t}</text>
          </g>
        ))}
        {xLabels.map((i) => (
          <text key={i} x={pts[i].x} y={H - 4} textAnchor={i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"}
            className="fill-muted font-mono text-[10px]">{label(days[i])}</text>
        ))}
        <path d={area} className="chart-fade fill-signal/10" />
        <path d={line} pathLength="1" className="chart-draw fill-none stroke-signal" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p, i) => (
          <g key={days[i].date} className="group">
            <rect x={p.x - slot / 2} y={box.y0} width={slot} height={box.y1 - box.y0} fill="transparent"
              onMouseEnter={(e) => show(e, `${label(days[i])} · ${values[i]}`)} />
            <line x1={p.x} x2={p.x} y1={box.y0} y2={box.y1} className="pointer-events-none stroke-rule opacity-0 group-hover:opacity-100" />
            <circle cx={p.x} cy={p.y} r="4" className="pointer-events-none fill-signal stroke-surface opacity-0 group-hover:opacity-100" strokeWidth="2" />
          </g>
        ))}
      </svg>
      <Tip tip={tip} />
    </ChartFrame>
  );
}

/** Answered vs not found (and degraded, when any): vertical bars that grow from the baseline. */
export function OutcomeBars({ totals }) {
  const [tip, show, hide] = useTip();
  const rows = [
    { label: "Answered", value: totals.answered, cls: "fill-signal" },
    { label: "Not in documents", value: totals.not_in_documents, cls: "fill-warn" },
    ...(totals.degraded ? [{ label: "Degraded", value: totals.degraded, cls: "fill-muted" }] : []),
  ];
  const w = 460;
  const h = 170;
  const pad = { l: 32, r: 8, t: 18, b: 22 };
  const top = niceMax(Math.max(...rows.map((r) => r.value), 0));
  const y = (v) => h - pad.b - (v / top) * (h - pad.b - pad.t);
  const band = (w - pad.l - pad.r) / rows.length;
  const barW = Math.min(56, band * 0.55);
  const total = totals.questions || 1;
  const summary = rows.map((r) => `${r.label}: ${r.value} (${Math.round((r.value / total) * 100)}%)`).join("; ") + ".";

  return (
    <ChartFrame title="Answered vs not found" summary={summary} table={rows.map((r) => [r.label, r.value])}>
      <svg viewBox={`0 0 ${w} ${h}`} className="block h-auto w-full overflow-visible" onMouseLeave={hide}>
        {ticks(top).map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} className="stroke-rule-soft" />
            <text x={pad.l - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted font-mono text-[10px]">{t}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const cx = pad.l + band * i + band / 2;
          const bh = Math.max(r.value ? 2 : 0, h - pad.b - y(r.value));
          return (
            <g key={r.label}>
              <rect x={cx - band / 2} y={pad.t} width={band} height={h - pad.t - pad.b} fill="transparent"
                onMouseEnter={(e) => show(e, `${r.label} · ${r.value} of ${totals.questions}`)} />
              <path
                d={`M${cx - barW / 2} ${h - pad.b} V${h - pad.b - bh + 4} q0 -4 4 -4 H${cx + barW / 2 - 4} q4 0 4 4 V${h - pad.b} Z`}
                className={`chart-grow-y pointer-events-none ${r.cls}`}
                style={{ animationDelay: `${i * 90}ms` }}
              />
              <text x={cx} y={h - pad.b - bh - 5} textAnchor="middle" className="chart-fade fill-ink font-mono text-[11px]">{r.value}</text>
              <text x={cx} y={h - 6} textAnchor="middle" className="fill-ink-soft text-[11px]">{r.label}</text>
            </g>
          );
        })}
        <line x1={pad.l} x2={w - pad.r} y1={h - pad.b} y2={h - pad.b} className="stroke-rule" />
      </svg>
      <Tip tip={tip} />
    </ChartFrame>
  );
}

/** Top cited documents: horizontal bars, name above each bar, count at the end. */
export function TopDocuments({ docs }) {
  const [tip, show, hide] = useTip();
  const rows = docs.slice(0, 5);
  const w = 460;
  const row = 34;
  const h = rows.length * row;
  const max = Math.max(1, ...rows.map((d) => d.answers));
  const trackW = w - 36;
  const summary = rows.map((d, i) => `${i + 1}. ${d.filename}, cited in ${d.answers} answer${d.answers === 1 ? "" : "s"}`).join("; ") + ".";

  return (
    <ChartFrame title="Top cited documents" summary={summary} table={rows.map((d) => [d.filename, d.answers])}>
      <svg viewBox={`0 0 ${w} ${h}`} className="block h-auto w-full overflow-visible" onMouseLeave={hide}>
        {rows.map((d, i) => {
          const y = i * row;
          const bw = Math.max(6, (d.answers / max) * trackW);
          return (
            <g key={d.filename}>
              <rect x="0" y={y} width={w} height={row} fill="transparent"
                onMouseEnter={(e) => show(e, `${d.filename} · ${d.answers} answer${d.answers === 1 ? "" : "s"}`)} />
              <text x="0" y={y + 11} className="pointer-events-none fill-ink text-[12px]">
                {d.filename.length > 52 ? `${d.filename.slice(0, 51)}…` : d.filename}
              </text>
              <rect x="0" y={y + 17} width={trackW} height="8" rx="4" className="pointer-events-none fill-rule-soft" />
              <rect x="0" y={y + 17} width={bw} height="8" rx="4" className="chart-grow-x pointer-events-none fill-source"
                style={{ animationDelay: `${i * 80}ms` }} />
              <text x={w} y={y + 25} textAnchor="end" className="chart-fade pointer-events-none fill-muted font-mono text-[11px]">{d.answers}</text>
            </g>
          );
        })}
      </svg>
      <Tip tip={tip} />
    </ChartFrame>
  );
}
