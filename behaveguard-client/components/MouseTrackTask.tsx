"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { TrackTrial, TrackSample } from "@/lib/types";
import { computeTrackingDerived } from "@/lib/kinematics";

const DOT_RADIUS = 14;
const SAMPLE_INTERVAL_MS = 16;

type Pattern = "sinusoidal" | "random_walk";

const PATTERNS: { id: Pattern; label: string; durationMs: number; blurb: string }[] = [
  {
    id: "sinusoidal",
    label: "smooth wave",
    durationMs: 20000,
    blurb: "the dot moves left and right in an oscillating pattern — match your cursor to it, don't click",
  },
  {
    id: "random_walk",
    label: "random drift",
    durationMs: 20000,
    blurb: "the dot follows a small unpredictable path — match your cursor to it, don't click",
  },
];

// position generators, parameterized by elapsed ms and area size
function sinusoidalPosition(elapsedMs: number, w: number, h: number) {
  const periodMs = 3000; // one left-right cycle every 3s
  const t = (elapsedMs % periodMs) / periodMs;
  const margin = DOT_RADIUS + 30;
  const x = margin + ((Math.sin(t * 2 * Math.PI - Math.PI / 2) + 1) / 2) * (w - margin * 2);
  const y = h / 2;
  return { x, y };
}

// random walk state kept across calls via closure in the component
function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

export default function MouseTrackTask({ onComplete, trialDurationMs = 20000 }: { onComplete: (trials: TrackTrial[]) => void; trialDurationMs?: number }) {
  const areaRef = useRef<HTMLDivElement>(null);
  const [patternIdx, setPatternIdx] = useState(0);
  const [phase, setPhase] = useState<"intro" | "running" | "between">("intro");
  const [target, setTarget] = useState({ x: 200, y: 200 });
  const [progressPct, setProgressPct] = useState(0);

  const trialsRef = useRef<TrackTrial[]>([]);
  const samplesRef = useRef<TrackSample[]>([]);
  const cursorRef = useRef({ x: 200, y: 200, pressure: 0.5 });
  const targetRef = useRef({ x: 200, y: 200 });
  const startedAtRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const lastSampleRef = useRef(0);
  // random-walk velocity state
  const rwVelRef = useRef({ x: 0, y: 0 });

  const currentPattern = useMemo(() => ({ ...PATTERNS[patternIdx], durationMs: trialDurationMs }), [patternIdx, trialDurationMs]);

  function handlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const rect = areaRef.current!.getBoundingClientRect();
    cursorRef.current = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      pressure: e.pressure ?? 0.5,
    };
  }

  const finishTrial = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    const samples = samplesRef.current;
    const trial: TrackTrial = {
      pattern: currentPattern.id,
      duration_ms: currentPattern.durationMs,
      started_at: startedAtRef.current,
      ended_at: performance.now(),
      samples,
      derived: computeTrackingDerived(samples),
    };
    trialsRef.current.push(trial);

    if (patternIdx + 1 >= PATTERNS.length) {
      onComplete(trialsRef.current);
    } else {
      setPhase("between");
      setTimeout(() => {
        setPatternIdx((i) => i + 1);
        setPhase("intro");
      }, 1400);
    }
  }, [currentPattern, patternIdx, onComplete]);

  const runFrame = useCallback(
    (now: number) => {
      const area = areaRef.current;
      if (!area) return;
      const { width, height } = area.getBoundingClientRect();
      const usableH = height - 30;
      const elapsed = now - startedAtRef.current;

      let pos: { x: number; y: number };
      if (currentPattern.id === "sinusoidal") {
        pos = sinusoidalPosition(elapsed, width, usableH);
        pos.y += 30;
      } else {
        // random walk: small random acceleration, damped velocity, bounded area
        const margin = DOT_RADIUS + 20;
        const accel = 0.9;
        rwVelRef.current.x = clamp(
          rwVelRef.current.x * 0.92 + (Math.random() - 0.5) * accel,
          -6,
          6
        );
        rwVelRef.current.y = clamp(
          rwVelRef.current.y * 0.92 + (Math.random() - 0.5) * accel,
          -6,
          6
        );
        const prev = targetRef.current;
        pos = {
          x: clamp(prev.x + rwVelRef.current.x, margin, width - margin),
          y: clamp(prev.y + rwVelRef.current.y, margin + 30, usableH + 30 - margin),
        };
      }

      targetRef.current = pos;
      setTarget(pos);

      if (now - lastSampleRef.current >= SAMPLE_INTERVAL_MS) {
        lastSampleRef.current = now;
        const c = cursorRef.current;
        const offset_x = c.x - pos.x;
        const offset_y = c.y - pos.y;
        samplesRef.current.push({
          cursor_x: c.x,
          cursor_y: c.y,
          target_x: pos.x,
          target_y: pos.y,
          offset_x,
          offset_y,
          distance_px: Math.hypot(offset_x, offset_y),
          ts: now,
          pressure: c.pressure,
        });
      }

      setProgressPct(Math.min(100, (elapsed / currentPattern.durationMs) * 100));

      if (elapsed >= currentPattern.durationMs) {
        finishTrial();
        return;
      }
      // Recursive animation-frame callbacks intentionally use the latest callback closure.
      // eslint-disable-next-line react-hooks/immutability
      rafRef.current = requestAnimationFrame(runFrame);
    },
    [currentPattern, finishTrial]
  );

  const startTrial = useCallback(() => {
    const area = areaRef.current;
    if (!area) return;
    const { width, height } = area.getBoundingClientRect();
    const initial = { x: width / 2, y: height / 2 };
    targetRef.current = initial;
    setTarget(initial);
    rwVelRef.current = { x: 0, y: 0 };
    samplesRef.current = [];
    startedAtRef.current = performance.now();
    lastSampleRef.current = 0;
    setProgressPct(0);
    setPhase("running");
    rafRef.current = requestAnimationFrame(runFrame);
  }, [runFrame]);

  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div className="flex-1 flex flex-col px-6 pb-6">
      <div className="max-w-3xl w-full mx-auto fade-up flex-1 flex flex-col">
        <div className="flex items-center justify-between mb-3 pt-2">
          <span className="font-mono-tight text-xs uppercase tracking-[0.3em] text-cyan">
            task 2 · track the target
          </span>
          <span className="font-mono-tight text-sm text-muted tabular-nums">
            {patternIdx + 1}/{PATTERNS.length} · {currentPattern.label}
          </span>
        </div>
        <div className="h-1 w-full bg-border rounded-full mb-4 overflow-hidden">
          <div
            className="h-full bg-cyan transition-all duration-150"
            style={{ width: `${phase === "running" ? progressPct : 0}%` }}
          />
        </div>

        <div
          ref={areaRef}
          onPointerMove={handlePointerMove}
          className="relative flex-1 min-h-[420px] bg-surface border border-border rounded-xl overflow-hidden cursor-crosshair"
        >
          {phase === "intro" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center px-6">
              <p className="font-mono-tight text-xs uppercase tracking-[0.3em] text-cyan">
                {currentPattern.label}
              </p>
              <p className="text-sm text-muted max-w-sm">{currentPattern.blurb}</p>
              <button
                onClick={startTrial}
                className="mt-2 px-5 py-2 rounded-lg bg-cyan text-bg font-mono-tight text-xs uppercase tracking-widest"
              >
                start
              </button>
            </div>
          )}

          {phase === "between" && (
            <div className="absolute inset-0 flex items-center justify-center">
              <p className="font-mono-tight text-xs uppercase tracking-[0.3em] text-muted">
                nice — next pattern loading
              </p>
            </div>
          )}

          {phase === "running" && (
            <>
              <p className="absolute top-3 left-1/2 -translate-x-1/2 text-xs text-muted font-mono-tight">
                stay on the dot, no clicking
              </p>
              <div
                style={{
                  left: target.x - DOT_RADIUS,
                  top: target.y - DOT_RADIUS,
                  width: DOT_RADIUS * 2,
                  height: DOT_RADIUS * 2,
                }}
                className="absolute rounded-full bg-cyan pointer-events-none"
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
