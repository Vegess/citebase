import { useEffect, useState } from "react";
import { useInView, usePrefersReducedMotion } from "../hooks/motion";

/*
 * Landing hero: a question goes in, two passages light up in the source
 * documents, and the answer writes itself with numbered citation chips.
 * A phase counter steps through the story; CSS transitions do the motion.
 * It loops gently, stops while off-screen, and with reduced motion it simply
 * shows the finished state.
 */

// How long each phase lasts before the next one starts (ms).
const PHASES = [500, 900, 800, 700, 800, 380, 380, 450, 380, 380, 3400, 700];
const FINAL = 10; // everything visible
const OUT = PHASES.length - 1; // fading out before the loop restarts

function plain(text) {
  return text.replace(/\*\*/g, "").replace(/\s*\[\d+\]/g, "");
}

function wrap(text, width, maxLines) {
  const lines = [];
  let line = "";
  for (const word of text.split(" ")) {
    if ((line + " " + word).trim().length > width) {
      lines.push(line);
      line = word;
    } else line = (line + " " + word).trim();
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    lines.length = maxLines;
    lines[maxLines - 1] = `${lines[maxLines - 1].replace(/\W*\w*$/, "")}…`;
  }
  return lines;
}

const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

const LINE_WIDTHS = [150, 120, 160, 100, 140];

function DocCard({ x, w, filename, highlights, phase }) {
  return (
    <g>
      <rect x={x} y="84" width={w} height="118" rx="8" className="fill-paper stroke-rule" />
      <text x={x + 14} y="104" className="fill-muted font-mono text-[10px]">{clip(filename, Math.floor(w / 6.4))}</text>
      {LINE_WIDTHS.map((lw, k) => {
        const hl = highlights.find((h) => h.line === k);
        const on = hl && phase >= hl.at && phase < OUT;
        const width = Math.min(lw * (w / 200), w - 46);
        return (
          <g key={k}>
            {hl && (
              <rect x={x + 8} y={117 + k * 16} width={width + 12} height="14" rx="3"
                className={`hero-t fill-source-soft ${on ? "opacity-100" : "opacity-0"}`} />
            )}
            <rect x={x + 14} y={121 + k * 16} width={width} height="6" rx="3"
              className={`hero-t ${on ? "fill-source" : "fill-rule"}`} />
            {hl && (
              <g className={`hero-t hero-pop ${on ? "is-on" : ""}`}>
                <circle cx={x + w - 18} cy={124 + k * 16} r="7" className="fill-source" />
                <text x={x + w - 18} y={124 + k * 16} dy="0.34em" textAnchor="middle" className="fill-white font-mono text-[9px]">{hl.n}</text>
              </g>
            )}
          </g>
        );
      })}
    </g>
  );
}

export function HeroAnimation({ demo }) {
  const reduced = usePrefersReducedMotion();
  const [ref, inView] = useInView({ threshold: 0.2 });
  const [phase, setPhase] = useState(reduced ? FINAL : 0);

  useEffect(() => {
    if (reduced) {
      setPhase(FINAL);
      return undefined;
    }
    if (!inView) return undefined; // paused off-screen; resumes where it was
    const t = setTimeout(() => setPhase((p) => (p + 1) % PHASES.length), PHASES[phase]);
    return () => clearTimeout(t);
  }, [phase, inView, reduced]);

  // A new audience restarts the story.
  useEffect(() => {
    if (!reduced) setPhase(0);
  }, [demo, reduced]);

  const show = (k) => phase >= k && phase < OUT;
  const two = demo.sources.length > 1;
  const highlights = two
    ? [[{ line: 1, n: 1, at: 3 }], [{ line: 3, n: 2, at: 4 }]]
    : [[{ line: 1, n: 1, at: 3 }, { line: 3, n: 2, at: 4 }]];
  const chips = two ? demo.sources.map((f, i) => [i + 1, f]) : [[1, demo.sources[0]], [2, demo.sources[0]]];
  const answer = wrap(plain(demo.a), 56, 3);
  const label = `Example: “${demo.q}” Two passages are found in ${demo.sources.join(" and ")}, then answered: ${plain(demo.a)}`;

  return (
    <figure ref={ref} className="rounded-xl bg-surface p-3 shadow-2xl ring-1 ring-black/5 sm:p-4">
      <svg viewBox="0 0 460 360" className="hero-anim block h-auto w-full" role="img" aria-label={label}>
        {/* Question */}
        <g className={`hero-t hero-slide ${show(1) ? "is-on" : ""}`}>
          <rect x="70" y="14" width="376" height="42" rx="12" className="fill-ink" />
          <text x="88" y="40" className="fill-paper text-[13px]">{clip(demo.q, 52)}</text>
        </g>

        {/* The question travelling into the documents */}
        <circle
          cx="258" cy="56" r="5"
          className={`hero-t hero-travel fill-signal ${phase === 2 ? "is-on" : ""}`}
        />

        {/* Documents */}
        {two ? (
          <>
            <DocCard x={14} w={208} filename={demo.sources[0]} highlights={highlights[0]} phase={phase} />
            <DocCard x={238} w={208} filename={demo.sources[1]} highlights={highlights[1]} phase={phase} />
          </>
        ) : (
          <DocCard x={14} w={432} filename={demo.sources[0]} highlights={highlights[0]} phase={phase} />
        )}

        {/* Answer */}
        <line x1="22" x2="22" y1="222" y2="346" className={`hero-t stroke-rule ${show(5) ? "opacity-100" : "opacity-0"}`} />
        {answer.map((line, i) => (
          <text key={i} x="36" y={238 + i * 20} className={`hero-t hero-rise fill-ink text-[13px] ${show(5 + i) ? "is-on" : ""}`}>
            {line}
          </text>
        ))}
        {chips.map(([n, file], i) => {
          const label = `${n}  ${clip(file, 24)}`;
          const cw = label.length * 6.4 + 18;
          const x = 36 + i * 200;
          return (
            <g key={n} className={`hero-t hero-pop ${show(8 + i) ? "is-on" : ""}`}>
              <rect x={x} y="306" width={cw} height="24" rx="3" className="fill-source-soft stroke-source/30" />
              <text x={x + 9} y="318" dy="0.34em" className="fill-source font-mono text-[11px]">{label}</text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
