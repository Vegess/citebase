/* Small, pure helpers for the hand-built SVG charts (tested in chartMath.test.js). */

/** Rounds a maximum up to 1, 2, 2.5 or 5 × 10^n so axis ticks land on round numbers. */
export function niceMax(value) {
  if (!(value > 0)) return 1;
  const pow = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * pow >= value);
  return step * pow;
}

/** Round axis ticks from 0 to niceMax(max): whole numbers for small counts, 4–5 steps otherwise. */
export function ticks(max) {
  const top = niceMax(max);
  if (top <= 5) return Array.from({ length: top + 1 }, (_, i) => i);
  const lead = top / 10 ** Math.floor(Math.log10(top));
  const n = lead === 2 ? 4 : 5;
  return Array.from({ length: n + 1 }, (_, i) => (top / n) * i);
}

/** Points for a series laid out across [x0, x1] × [y1 (bottom), y0 (top)]. */
export function linePoints(values, { x0, x1, y0, y1, max }) {
  const top = max || niceMax(Math.max(...values, 0));
  const span = values.length > 1 ? (x1 - x0) / (values.length - 1) : 0;
  return values.map((v, i) => ({
    x: values.length > 1 ? x0 + span * i : (x0 + x1) / 2,
    y: y1 - (v / top) * (y1 - y0),
  }));
}

/** SVG path "M x y L x y ..." through the points. */
export function pathFrom(points) {
  return points.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
}

/** Plain-language summary of a daily series, for screen readers. */
export function describeDaily(days) {
  if (!days.length) return "No data.";
  const total = days.reduce((s, d) => s + d.questions, 0);
  const busiest = days.reduce((a, b) => (b.questions > a.questions ? b : a));
  return `${total} question${total === 1 ? "" : "s"} over ${days.length} days, from ${days[0].date} to ${
    days[days.length - 1].date
  }. Busiest day: ${busiest.date} with ${busiest.questions}.`;
}

/** Documents pipeline: how far a status has got. failed → the stage it stopped at is unknown, show stage 1. */
export const PIPELINE = ["Uploaded", "Read", "Split", "Indexed", "Ready"];
export function pipelineProgress(status) {
  switch (status) {
    case "queued": return { done: 1, active: 1, failed: false };
    case "chunking": return { done: 2, active: 2, failed: false };
    case "embedding": return { done: 3, active: 3, failed: false };
    case "ready":
    case "superseded": return { done: 5, active: -1, failed: false };
    case "failed":
    case "reupload_required": return { done: 1, active: 1, failed: true };
    default: return { done: 1, active: -1, failed: false };
  }
}
