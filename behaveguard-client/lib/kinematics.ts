import { KeyEvent, KeyboardExtras, PathPoint, PathKinematics, TrackSample, TrackingDerived } from "./types";

// ─── PATH KINEMATICS ───────────────────────────────────────────────────────

export function computePathKinematics(
  path: PathPoint[],
  targetX: number,
  targetY: number,
  targetRadius: number
): PathKinematics {
  if (path.length < 2) {
    return {
      velocities: [],
      accelerations: [],
      jerks: [],
      sub_movement_count: 0,
      angle_of_approach_deg: 0,
      hover_dwell_ms: 0,
    };
  }

  // velocities (px/s) between consecutive points
  const velocities: number[] = [];
  for (let i = 1; i < path.length; i++) {
    const dt = (path[i].ts - path[i - 1].ts) / 1000;
    const dist = Math.hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y);
    velocities.push(dt > 0 ? dist / dt : 0);
  }

  // accelerations (px/s²)
  const accelerations: number[] = [];
  for (let i = 1; i < velocities.length; i++) {
    const dt = (path[i].ts - path[i - 1].ts) / 1000;
    accelerations.push(dt > 0 ? (velocities[i] - velocities[i - 1]) / dt : 0);
  }

  // jerks (px/s³)
  const jerks: number[] = [];
  for (let i = 1; i < accelerations.length; i++) {
    const dt = (path[i].ts - path[i - 1].ts) / 1000;
    jerks.push(dt > 0 ? (accelerations[i] - accelerations[i - 1]) / dt : 0);
  }

  // sub-movements: count direction reversals in velocity profile
  let sub_movement_count = 0;
  for (let i = 1; i < velocities.length - 1; i++) {
    if (velocities[i] < velocities[i - 1] && velocities[i] < velocities[i + 1]) {
      sub_movement_count++;
    }
  }

  // angle of approach: bearing over final 20% of path toward target
  const tailStart = Math.max(0, Math.floor(path.length * 0.8));
  const tail = path.slice(tailStart);
  let angle_of_approach_deg = 0;
  if (tail.length >= 2) {
    const dx = targetX - tail[0].x;
    const dy = targetY - tail[0].y;
    angle_of_approach_deg = Math.round((Math.atan2(dy, dx) * 180) / Math.PI);
  }

  // hover dwell: cumulative time cursor was within 2× target radius before click
  const hoverRadius = targetRadius * 2;
  let hover_dwell_ms = 0;
  for (let i = 1; i < path.length; i++) {
    const dist = Math.hypot(path[i].x - targetX, path[i].y - targetY);
    if (dist <= hoverRadius) {
      hover_dwell_ms += path[i].ts - path[i - 1].ts;
    }
  }

  return {
    velocities: velocities.map((v) => Math.round(v)),
    accelerations: accelerations.map((a) => Math.round(a)),
    jerks: jerks.map((j) => Math.round(j)),
    sub_movement_count,
    angle_of_approach_deg,
    hover_dwell_ms: Math.round(hover_dwell_ms),
  };
}

// ─── TRACKING DERIVED STATS ─────────────────────────────────────────────────

export function computeTrackingDerived(samples: TrackSample[]): TrackingDerived {
  const empty: TrackingDerived = {
    mean_error_px: 0,
    rms_error_px: 0,
    lag_ms: 0,
    prediction_ratio: 0,
    tremor_px: 0,
    correlation_x: 0,
    correlation_y: 0,
    error_first_half_px: 0,
    error_second_half_px: 0,
    fatigue_delta_px: 0,
  };
  if (samples.length < 4) return empty;

  // mean / rms error
  const dists = samples.map((s) => s.distance_px);
  const mean_error_px = dists.reduce((a, b) => a + b, 0) / dists.length;
  const rms_error_px = Math.sqrt(dists.reduce((a, b) => a + b * b, 0) / dists.length);

  // approximate sample interval (ms)
  const dt =
    samples.length > 1
      ? (samples[samples.length - 1].ts - samples[0].ts) / (samples.length - 1)
      : 16;

  // lag via cross-correlation: shift target series against cursor series,
  // find shift (in samples) that minimizes mean distance error on the x-axis
  const maxShift = Math.min(30, Math.floor(samples.length / 4)); // ~480ms at 16ms sampling
  let bestShift = 0;
  let bestErr = Infinity;
  for (let shift = -maxShift; shift <= maxShift; shift++) {
    let err = 0;
    let count = 0;
    for (let i = 0; i < samples.length; i++) {
      const j = i + shift;
      if (j < 0 || j >= samples.length) continue;
      const dx = samples[i].cursor_x - samples[j].target_x;
      const dy = samples[i].cursor_y - samples[j].target_y;
      err += Math.hypot(dx, dy);
      count++;
    }
    if (count > 0) {
      const avg = err / count;
      if (avg < bestErr) {
        bestErr = avg;
        bestShift = shift;
      }
    }
  }
  // positive shift means cursor[i] best matches target[i+shift] i.e. cursor is behind (lagging)
  const lag_ms = Math.round(bestShift * dt);

  // prediction ratio: fraction of samples where cursor is "ahead" of target
  // (cursor's instantaneous direction-projected position leads target's recent motion)
  let leadCount = 0;
  for (let i = 1; i < samples.length; i++) {
    const targetMoveX = samples[i].target_x - samples[i - 1].target_x;
    const targetMoveY = samples[i].target_y - samples[i - 1].target_y;
    const cursorAheadX = samples[i].cursor_x - samples[i].target_x;
    const cursorAheadY = samples[i].cursor_y - samples[i].target_y;
    const dot = targetMoveX * cursorAheadX + targetMoveY * cursorAheadY;
    if (dot > 0) leadCount++;
  }
  const prediction_ratio = parseFloat((leadCount / (samples.length - 1)).toFixed(3));

  // tremor: RMS of high-frequency component of cursor path (2nd derivative-ish jitter),
  // computed as RMS of deviation from a short moving-average of the cursor path
  const window = 5;
  let tremorSumSq = 0;
  let tremorCount = 0;
  for (let i = 0; i < samples.length; i++) {
    const lo = Math.max(0, i - window);
    const hi = Math.min(samples.length - 1, i + window);
    let sx = 0,
      sy = 0,
      n = 0;
    for (let k = lo; k <= hi; k++) {
      sx += samples[k].cursor_x;
      sy += samples[k].cursor_y;
      n++;
    }
    const avgX = sx / n;
    const avgY = sy / n;
    const dx = samples[i].cursor_x - avgX;
    const dy = samples[i].cursor_y - avgY;
    tremorSumSq += dx * dx + dy * dy;
    tremorCount++;
  }
  const tremor_px = parseFloat(Math.sqrt(tremorSumSq / tremorCount).toFixed(3));

  // pearson correlation helper
  function pearson(a: number[], b: number[]): number {
    const n = a.length;
    const meanA = a.reduce((x, y) => x + y, 0) / n;
    const meanB = b.reduce((x, y) => x + y, 0) / n;
    let num = 0,
      denA = 0,
      denB = 0;
    for (let i = 0; i < n; i++) {
      const da = a[i] - meanA;
      const db = b[i] - meanB;
      num += da * db;
      denA += da * da;
      denB += db * db;
    }
    const den = Math.sqrt(denA * denB);
    return den === 0 ? 0 : num / den;
  }
  const correlation_x = parseFloat(
    pearson(samples.map((s) => s.cursor_x), samples.map((s) => s.target_x)).toFixed(3)
  );
  const correlation_y = parseFloat(
    pearson(samples.map((s) => s.cursor_y), samples.map((s) => s.target_y)).toFixed(3)
  );

  // fatigue: compare mean error in first half vs second half
  const half = Math.floor(samples.length / 2);
  const firstHalf = dists.slice(0, half);
  const secondHalf = dists.slice(half);
  const error_first_half_px = firstHalf.length
    ? firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length
    : 0;
  const error_second_half_px = secondHalf.length
    ? secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length
    : 0;

  return {
    mean_error_px: Math.round(mean_error_px),
    rms_error_px: Math.round(rms_error_px),
    lag_ms,
    prediction_ratio,
    tremor_px,
    correlation_x,
    correlation_y,
    error_first_half_px: Math.round(error_first_half_px),
    error_second_half_px: Math.round(error_second_half_px),
    fatigue_delta_px: Math.round(error_second_half_px - error_first_half_px),
  };
}

export function computeKeyboardExtras(events: KeyEvent[]): KeyboardExtras {
  const alphaEvents = events
    .filter((e) => e.key_category === "alphanum" || e.key_category === "space")
    .sort((a, b) => a.press_ts - b.press_ts);

  // IKI sequence
  const iki_sequence: number[] = [];
  for (let i = 1; i < alphaEvents.length; i++) {
    const iki = alphaEvents[i].press_ts - alphaEvents[i - 1].press_ts;
    if (iki >= 0 && iki < 2000) iki_sequence.push(Math.round(iki));
  }

  // trigraph timings — 3-key windows of alphanum keys
  const trigraphMap = new Map<string, number[]>();
  for (let i = 2; i < alphaEvents.length; i++) {
    const triplet = [alphaEvents[i - 2], alphaEvents[i - 1], alphaEvents[i]];
    const key = triplet.map((e) => e.key_id).join("");
    if (key.includes("other")) continue;
    const span = triplet[2].press_ts - triplet[0].press_ts;
    if (span < 0 || span > 3000) continue;
    if (!trigraphMap.has(key)) trigraphMap.set(key, []);
    trigraphMap.get(key)!.push(Math.round(span));
  }
  const trigraph_timings: Record<string, number> = {};
  trigraphMap.forEach((arr, key) => {
    if (arr.length >= 2) {
      trigraph_timings[key] = Math.round(arr.reduce((a, b) => a + b, 0) / arr.length);
    }
  });

  // backspace pattern
  const backspaceEvents = events.filter((e) => e.key_id === "backspace");
  const backspace_count = backspaceEvents.length;
  // estimate position: count alphanum/space events before each backspace
  const backspace_positions: number[] = backspaceEvents.map((bs) => {
    return events
      .filter((e) => e.press_ts < bs.press_ts && (e.key_category === "alphanum" || e.key_category === "space"))
      .length;
  });

  // drift: IKI mean of first half vs second half
  let drift_iki_ms = 0;
  if (iki_sequence.length >= 10) {
    const half = Math.floor(iki_sequence.length / 2);
    const firstHalf = iki_sequence.slice(0, half);
    const secondHalf = iki_sequence.slice(half);
    const mean = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
    drift_iki_ms = Math.round(mean(secondHalf) - mean(firstHalf));
  }

  // cyclical time encoding for hour-of-day
  const now = new Date();
  const hourFraction = now.getHours() + now.getMinutes() / 60;
  const time_sin = parseFloat(Math.sin((2 * Math.PI * hourFraction) / 24).toFixed(4));
  const time_cos = parseFloat(Math.cos((2 * Math.PI * hourFraction) / 24).toFixed(4));

  return {
    iki_sequence,
    trigraph_timings,
    backspace_positions,
    backspace_count,
    drift_iki_ms,
    time_sin,
    time_cos,
  };
}
