// Run with: npm test  (node's built-in test runner; no extra dependencies)
import { test } from "node:test";
import assert from "node:assert/strict";
import { describeDaily, linePoints, niceMax, pathFrom, pipelineProgress, ticks } from "./chartMath.js";

test("niceMax rounds up to 1/2/2.5/5 x 10^n", () => {
  assert.equal(niceMax(0), 1);
  assert.equal(niceMax(3), 5);
  assert.equal(niceMax(7), 10);
  assert.equal(niceMax(18), 20);
  assert.equal(niceMax(23), 25);
  assert.equal(niceMax(140), 200);
});

test("ticks are whole and evenly spaced", () => {
  assert.deepEqual(ticks(0), [0, 1]);
  assert.deepEqual(ticks(3), [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(ticks(18), [0, 5, 10, 15, 20]);
  assert.deepEqual(ticks(40), [0, 10, 20, 30, 40, 50]);
  for (const max of [1, 6, 9, 23, 77, 140, 999]) {
    assert.ok(ticks(max).every(Number.isInteger), `integer ticks for ${max}`);
    assert.ok(ticks(max).at(-1) >= max);
  }
});

test("linePoints maps values into the plot box", () => {
  const pts = linePoints([0, 5, 10], { x0: 10, x1: 110, y0: 0, y1: 100, max: 10 });
  assert.deepEqual(pts, [{ x: 10, y: 100 }, { x: 60, y: 50 }, { x: 110, y: 0 }]);
  assert.equal(pathFrom(pts), "M10.0 100.0 L60.0 50.0 L110.0 0.0");
  assert.deepEqual(linePoints([4], { x0: 0, x1: 100, y0: 0, y1: 10, max: 4 }), [{ x: 50, y: 0 }]);
});

test("describeDaily summarises the series", () => {
  const text = describeDaily([{ date: "2026-11-01", questions: 2 }, { date: "2026-11-02", questions: 5 }]);
  assert.equal(text, "7 questions over 2 days, from 2026-11-01 to 2026-11-02. Busiest day: 2026-11-02 with 5.");
});

test("pipelineProgress follows the document lifecycle", () => {
  assert.equal(pipelineProgress("queued").done, 1);
  assert.equal(pipelineProgress("chunking").done, 2);
  assert.equal(pipelineProgress("embedding").done, 3);
  assert.deepEqual(pipelineProgress("ready"), { done: 5, active: -1, failed: false });
  assert.equal(pipelineProgress("failed").failed, true);
});
