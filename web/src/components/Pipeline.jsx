import { PIPELINE, pipelineProgress } from "../lib/chartMath";

/*
 * uploaded → read → split → indexed → ready, as five nodes on a rail. The filled
 * rail eases to the document's current stage (CSS transition on stroke-dashoffset),
 * the active node pulses, and a failed document shows a red node where it stopped.
 */
export function Pipeline({ status }) {
  const { done, active, failed } = pipelineProgress(status);
  const gap = 22;
  const w = gap * (PIPELINE.length - 1) + 8;
  const fraction = (done - 1) / (PIPELINE.length - 1);
  const label = failed
    ? `Processing stopped after: ${PIPELINE[done - 1]}`
    : done === PIPELINE.length
      ? "Processing complete: ready"
      : `Processing: ${PIPELINE[done - 1]} done, now ${PIPELINE[active]}`;

  return (
    <svg viewBox={`0 0 ${w} 10`} width={w} height="10" role="img" aria-label={label} className="pipeline shrink-0 overflow-visible">
      <title>{label}</title>
      <line x1="4" x2={w - 4} y1="5" y2="5" className="stroke-rule" strokeWidth="2" strokeLinecap="round" />
      <line
        x1="4" x2={w - 4} y1="5" y2="5" pathLength="1"
        className={`pipeline-fill ${failed ? "stroke-danger" : "stroke-source"}`}
        strokeWidth="2" strokeLinecap="round" strokeDasharray="1 1" style={{ strokeDashoffset: 1 - fraction }}
      />
      {PIPELINE.map((stage, i) => {
        const reached = i < done;
        const isActive = i === active && !failed;
        const isFailed = failed && i === done;
        return (
          <circle
            key={stage}
            cx={4 + gap * i} cy="5" r={isActive || isFailed ? 3.5 : 3}
            className={`pipeline-node ${
              isFailed ? "fill-danger" : reached ? "fill-source" : isActive ? "fill-surface stroke-source pipeline-pulse" : "fill-surface stroke-rule"
            }`}
            strokeWidth="1.5"
            style={{ transitionDelay: `${i * 80}ms` }}
          >
            <title>{stage}</title>
          </circle>
        );
      })}
    </svg>
  );
}
