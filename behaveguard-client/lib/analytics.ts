import { KeyEvent, DotTrial, DragTrial } from "./types";

export function dwellTimes(events: KeyEvent[]): number[] {
  return events
    .filter((e) => e.release_ts != null && e.key_category !== "special")
    .map((e) => (e.release_ts as number) - e.press_ts)
    .filter((v) => v > 0 && v < 1000);
}

export function flightTimes(events: KeyEvent[]): number[] {
  const sorted = events
    .filter((e) => e.key_category !== "special")
    .sort((a, b) => a.press_ts - b.press_ts);
  const out: number[] = [];
  for (let i = 1; i < sorted.length; i++) {
    const ft = sorted[i].press_ts - (sorted[i - 1].release_ts ?? sorted[i - 1].press_ts);
    if (ft >= 0 && ft < 2000) out.push(ft);
  }
  return out;
}

export function topDigraphs(events: KeyEvent[], n = 10): { pair: string; avg_ms: number; count: number }[] {
  const sorted = events
    .filter((e) => e.key_category === "alphanum")
    .sort((a, b) => a.press_ts - b.press_ts);
  const map = new Map<string, number[]>();
  for (let i = 1; i < sorted.length; i++) {
    const dt = sorted[i].press_ts - sorted[i - 1].press_ts;
    if (dt < 0 || dt > 1500) continue;
    const pair = `${sorted[i - 1].key_id}${sorted[i].key_id}`;
    if (!map.has(pair)) map.set(pair, []);
    map.get(pair)!.push(dt);
  }
  return Array.from(map.entries())
    .map(([pair, arr]) => ({ pair, avg_ms: arr.reduce((a, b) => a + b, 0) / arr.length, count: arr.length }))
    .filter((d) => d.count >= 2)
    .sort((a, b) => b.count - a.count)
    .slice(0, n);
}

// rolling WPM over time, bucketed into ~10 windows across the typing session
export function wpmSeries(events: KeyEvent[], startTs: number, endTs: number, buckets = 12) {
  const span = Math.max(endTs - startTs, 1);
  const bucketMs = span / buckets;
  const counts = new Array(buckets).fill(0);
  events
    .filter((e) => e.key_category === "alphanum" || e.key_category === "space")
    .forEach((e) => {
      const idx = Math.min(buckets - 1, Math.floor((e.press_ts - startTs) / bucketMs));
      if (idx >= 0) counts[idx]++;
    });
  return counts.map((c, i) => ({
    t: Math.round(((i + 1) * bucketMs) / 1000),
    wpm: Math.round((c / 5) / (bucketMs / 1000 / 60)),
  }));
}

export function mean(arr: number[]): number {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

export function histogram(arr: number[], binCount = 12) {
  if (!arr.length) return [] as { bin: string; count: number }[];
  const min = Math.min(...arr);
  const max = Math.max(...arr);
  const width = Math.max((max - min) / binCount, 1);
  const bins = new Array(binCount).fill(0);
  arr.forEach((v) => {
    const idx = Math.min(binCount - 1, Math.floor((v - min) / width));
    bins[idx]++;
  });
  return bins.map((count, i) => ({
    bin: Math.round(min + i * width).toString(),
    count,
  }));
}

export function dotMetrics(trials: DotTrial[]) {
  const travel = trials.map((t) => t.travel_time_ms);
  const error = trials.map((t) => t.error_px);
  const velocities = trials.map((t) => {
    if (t.path.length < 2) return 0;
    const distance = pathLength(t.path);
    const dur = (t.path[t.path.length - 1].ts - t.path[0].ts) / 1000;
    return dur > 0 ? distance / dur : 0;
  });
  return {
    avg_travel_ms: mean(travel),
    avg_error_px: mean(error),
    avg_velocity_pxs: mean(velocities),
    travel,
    error,
    velocities,
  };
}

function pathLength(path: { x: number; y: number }[]) {
  let d = 0;
  for (let i = 1; i < path.length; i++) {
    d += Math.hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y);
  }
  return d;
}

export function dragMetrics(trials: DragTrial[]) {
  const durations = trials.map((t) => t.duration_ms);
  const successRate = trials.length ? trials.filter((t) => t.success).length / trials.length : 0;
  return { avg_duration_ms: mean(durations), success_rate: successRate };
}
